"""调度层：日历 → 状态机 → 指令队列（PRD §4.2 调度层，纯 Python 无 LLM）

时间线（每 tick 一次）：
  t1  sync_calendar()            拉 Graph Mock → 覆盖写 store.meetings
  t2  遍历"已绑定设备"，定位其房间的会议
  t3  进 prepare 窗口（会前 10min ≤ now < 开始）→ 入队 PREPARE_MEETING（去重）
  t4  会议已结束且发过 PREPARE → 入队 REPLAY_DEFAULT（去重）
  ───
  ★ 闭环：指令进队列 → 设备 poll 取走 → ACK 回执进审计流

演示参数：TICK_SEC 默认 60 秒（生产按 PRD 走 300 秒），可用环境变量覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

import secrets

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import graph_client, mailer
from app.content import build_meeting_content, is_sensitive
from app.layouts import layout_page, pick_layout
from app.settings import (
    LINK_WINDOW_DAYS,
    PREPARE_LEAD_MIN,
    PUBLIC_BASE,
    SIGNAGE_SLOTS,
    SWITCH_LEAD_MIN,
    TICK_SEC,
    UPLOAD_LEAD_MIN,
)
from app.store import (
    Device,
    Meeting,
    UploadToken,
    shift_minutes,
    store,
    utc_now_iso,
)
from app.tz import to_local

_scheduler: AsyncIOScheduler | None = None


def sync_calendar() -> int:
    """把 Graph Mock 的日程同步进 store。

    得到的数据：
        无入参（fixture 以当前时刻为基准生成）。

    要做的操作：
        调 graph_client.fetch_events()（Mock 或真 Graph，上层无感）；
        转 Meeting 行（带参会人、敏感标记），按 meeting_id 覆盖写。

    返回：
        本次同步的会议条数，如 5。

    为什么：状态机只认 store 里的会议，先把"日历"落成本地缓存（对应 F2.4 定时拉取）；
            敏感标记在同步时就落库，避免每次下发再判一遍漏判。
    """
    events = graph_client.fetch_events()
    for event in events:
        store.upsert_meeting(Meeting(
            meeting_id=event["meeting_id"],
            room_id=event["room_id"],
            subject=event["subject"],
            organizer_email=event["organizer_email"],
            attendees=event.get("attendees", []),
            start_time_utc=event["start_time_utc"],
            end_time_utc=event["end_time_utc"],
            timezone=event["timezone"],
            status=event["status"],
            is_sensitive=is_sensitive(event["subject"]),
        ))
    return len(events)


def content_url_of(meeting: Meeting) -> str:
    """拼会议页地址（设备直接打开就能渲染）。

    得到的数据：
        meeting（Meeting 行，含标题/参会人/时区/起止时间）。

    要做的操作：
        先过内容生成（敏感判定 + 模板文案 + 本地时间），
        再把生成结果塞进 /ui/display/meeting.html 的 query。

    返回：
        "http://localhost:8000/ui/display/meeting.html?subject=产品评审会&room=room-a3-01
         &tz=Asia%2FShanghai&time=10%3A00+%E2%80%93+11%3A00&organizer=zhangsan&attendees=..."

    为什么：设备端只负责"打开 URL"（PRD A4），文案与脱敏都在服务端算完，
            敏感会议的标题在 URL 里就已经是「会议中」，不可能泄露到设备。
    """
    content = build_meeting_content(meeting)
    layout = pick_layout(content)
    # 版式差异体现在页面上（minimal/focus/standard），设备只负责打开这个 URL
    page = layout_page(layout)
    query = urlencode({
        "meeting_id": meeting.meeting_id,
        "subject": content["title"],
        "tagline": content["tagline"],
        "room": meeting.room_id,
        "tz": meeting.timezone,
        "time": content["time_label"],
        "organizer": content["organizer"],
        "attendees": ",".join(content["attendees"]),
        "sensitive": "1" if content["is_sensitive"] else "0",
        "layout": layout,
        "start": meeting.start_time_utc,
        "end": meeting.end_time_utc,
    })
    return f"{PUBLIC_BASE}{page}{'&' if '?' in page else '?'}{query}"


def _prepare_payload(meeting: Meeting) -> dict:
    """PREPARE_MEETING 的 payload（规范 §4.4 字段全集）。

    得到的数据：
        meeting（Meeting 行）。

    要做的操作：
        算 prepare_at（会前 10min）、switch_at（会前 1min），带上 until=会议结束。

    返回：
        {"content_url": "...", "meeting_id": "meeting_a3_01_0",
         "prepare_at": "2026-10-27T09:58:00Z", "switch_at": "2026-10-27T10:07:00Z",
         "timezone": "Asia/Shanghai", "until": "2026-10-27T11:08:00Z"}

    为什么：切屏是设备本地按 switch_at 定时执行（自动切换唯一路径），服务端只下发时刻。
    """
    return {
        "content_url": content_url_of(meeting),
        "meeting_id": meeting.meeting_id,
        "prepare_at": shift_minutes(meeting.start_time_utc, -PREPARE_LEAD_MIN),
        "switch_at": shift_minutes(meeting.start_time_utc, -SWITCH_LEAD_MIN),
        "timezone": meeting.timezone,
        "until": meeting.end_time_utc,
    }


def signage_slot(meeting: Meeting) -> dict:
    """按会议室本地时间选标牌时段（F3.4）。

    得到的数据：
        meeting（刚结束的会议，用它的时区判断当前是几点）。

    要做的操作：
        把"当前 UTC"换算到会议室本地小时，匹配 SIGNAGE_SLOTS 的区间。

    返回：
        {"name": "afternoon", "label": "下午标牌", "playlist": "brand_afternoon"}

    为什么：早/中/晚三套标牌是 PRD 的 P0 策略，且必须按会议室本地时区算——
            纽约的下午不能因为服务器在上海就显示夜间标牌。
    """
    local_hour = to_local(utc_now_iso(), meeting.timezone).hour
    for slot in SIGNAGE_SLOTS:
        if slot["start_hour"] <= local_hour < slot["end_hour"]:
            return slot
    return SIGNAGE_SLOTS[0]


def _replay_payload(meeting: Meeting) -> dict:
    """REPLAY_DEFAULT 的 payload。

    得到的数据：
        meeting（刚结束的会议）。

    要做的操作：
        组标牌恢复指令：时段标牌 + 标牌页 url + timezone + meeting_id（去重/审计用）。

    返回：
        {"playlist": ["brand_afternoon"], "slot": "afternoon",
         "signage_url": "http://localhost:8000/ui/display/signage.html?slot=afternoon",
         "timezone": "Asia/Shanghai", "meeting_id": "meeting_a3_01_0"}

    为什么：会议结束必须把屏切回标牌（PRD 场景 A 11:00 那一步），
            且要回"这个时段该放的"标牌，而不是永远同一张。
    """
    slot = signage_slot(meeting)
    signage_url = f"{PUBLIC_BASE}/ui/display/signage.html?slot={slot['name']}"
    return {
        "playlist": [slot["playlist"]],
        "slot": slot["name"],
        "signage_url": signage_url,
        "timezone": meeting.timezone,
        "meeting_id": meeting.meeting_id,
    }


def expire_materials() -> int:
    """清理到期的会议专属素材（F4.8 双侧清理的服务端侧）。

    得到的数据：
        无（时间取 utc_now_iso()）。

    要做的操作：
        找 expire_at ≤ 现在的专属素材；
        逐个删记录 + 删磁盘文件；
        向该会议所在会议室的设备下发 CLEAN_MATERIAL（同一场会只发一次）。

    返回：
        本次清理的素材数量，如 2。

    为什么：专属素材不能只靠设备 15 天 LRU，会后必须在服务端清 + 通知设备清，
            否则下一场会可能读到上一场的残留（PRD 场景 E 补丁）。
    """
    from app.files import remove_file  # 局部导入：避免与 files → settings 的导入顺序耦合

    now = utc_now_iso()
    cleaned = 0
    for material in store.expired_meeting_materials(now):
        meeting = store.get_meeting(material.meeting_id) if material.meeting_id else None
        remove_file(material.file_path)
        store.delete_material(material.material_id)
        cleaned += 1
        if meeting is None:
            continue
        for device in store.devices_in_room(meeting.room_id):
            # 同一场会只下发一次清理指令（重复 tick 不重复入队）
            if store.has_command(device.device_id, "CLEAN_MATERIAL", meeting.meeting_id):
                continue
            store.enqueue_command(
                device_id=device.device_id,
                type_="CLEAN_MATERIAL",
                payload={
                    "material_ids": [material.material_id],
                    "scope": "meeting",
                    "meeting_id": meeting.meeting_id,
                },
                initiated_by="system",
            )
    if cleaned:
        print(f"[scheduler] 到期清理专属素材 {cleaned} 条")
    return cleaned


def evaluate_device(device: Device, now_iso: str) -> list[str]:
    """单台设备的状态机判定（IDLE/MEETING_PREP/MEETING 的指令侧）。

    得到的数据：
        device（设备行，必须有 room_id）；now_iso（当前 UTC 时间串）。

    要做的操作：
        取该房间全部 scheduled 会议；
        prepare 窗口内且未发过 PREPARE → 入队；
        已结束、发过 PREPARE、未发过 REPLAY → 入队 REPLAY。

    返回：
        本次下发的指令描述列表，如 ["PREPARE_MEETING meeting_a3_01_0"]；无则 []。

    为什么：一台设备一次 tick 只该收到它房间该收的指令，判定收口在这一个函数里好测。
    """
    if device.room_id is None:
        return []

    issued: list[str] = []
    for meeting in store.meetings_of_room(device.room_id):
        if meeting.status != "scheduled":
            continue
        prepare_at = shift_minutes(meeting.start_time_utc, -PREPARE_LEAD_MIN)

        # ① 预拉取窗口：会前 10 分钟内、还没开会
        in_prepare_window = prepare_at <= now_iso < meeting.start_time_utc
        if in_prepare_window and not store.has_command(device.device_id, "PREPARE_MEETING", meeting.meeting_id):
            store.enqueue_command(
                device_id=device.device_id,
                type_="PREPARE_MEETING",
                payload=_prepare_payload(meeting),
                initiated_by="system",
            )
            issued.append(f"PREPARE_MEETING {meeting.meeting_id}")

        # ② 会议结束：恢复标牌（要求本场确实发过 PREPARE，避免空转）
        ended = now_iso >= meeting.end_time_utc
        prepared = store.has_command(device.device_id, "PREPARE_MEETING", meeting.meeting_id)
        replayed = store.has_command(device.device_id, "REPLAY_DEFAULT", meeting.meeting_id)
        if ended and prepared and not replayed:
            store.enqueue_command(
                device_id=device.device_id,
                type_="REPLAY_DEFAULT",
                payload=_replay_payload(meeting),
                initiated_by="system",
            )
            issued.append(f"REPLAY_DEFAULT {meeting.meeting_id}")

    return issued


def ensure_upload_links() -> int:
    """为窗口内的新会议生成免登录上传链接并邮件通知定会者（F2.4 / F4.7）。

    得到的数据：
        无（窗口取 LINK_WINDOW_DAYS 天，只看未开始的 scheduled 会议）。

    要做的操作：
        遍历未来窗口内、且上传截止时间还没过的会议；
        没有 token 的 → 生成随机 token（max_uses=50，会后失效）；
        调 mailer.send_upload_link 投递（MAIL_MOCK 时只落日志）。

    返回：
        本次新发的链接数量，如 2。

    为什么：定会者不会自己找入口，服务端必须在发现新会议后主动把链接发出去；
            已有 token 的跳过，避免每 30 分钟重复发信；
            上传截止早于当前时刻的会议跳过——那种链接发出去点开就是 2006「已截止」，
            等于发了一封没用的邮件（实测首场会 8 分钟后开，链接一生成就已作废）。
    """
    now = utc_now_iso()
    horizon = shift_minutes(now, LINK_WINDOW_DAYS * 24 * 60)
    sent = 0
    for meeting in store.all_meetings():
        if meeting.status != "scheduled":
            continue
        if not (now < meeting.start_time_utc <= horizon):
            continue
        # 上传截止 = 会前 UPLOAD_LEAD_MIN 分钟；已经过了就别发废链接
        if now >= shift_minutes(meeting.start_time_utc, -UPLOAD_LEAD_MIN):
            continue
        if store.token_for_meeting(meeting.meeting_id) is not None:
            continue
        token = f"tok_{secrets.token_urlsafe(12)}"
        store.add_upload_token(UploadToken(
            token=token,
            meeting_id=meeting.meeting_id,
            organizer_email=meeting.organizer_email,
            expire_at=meeting.end_time_utc,
        ))
        mailer.send_upload_link(meeting, token)
        sent += 1
    if sent:
        print(f"[scheduler] 新生成上传链接 {sent} 条并发邮件（mock={mailer.MAIL_MOCK}）")
    return sent


def tick(resync: bool = True) -> dict:
    """一次完整调度（同步日历 + 全设备状态机）。

    得到的数据：
        resync（True=先拉日历覆盖本地缓存；False=沿用当前缓存，供测试模拟"时间流逝"）。

    要做的操作：
        t1 resync 为真时 sync_calendar()
        t2 遍历已绑定设备逐台 evaluate_device()
        t3 汇总本次下发的指令，打日志

    返回：
        {"synced": 5, "commands": 2, "detail": ["SH-A3-01-01 → PREPARE_MEETING meeting_a3_01_0"]}

    为什么：调度器只需按固定节拍调这一个函数；测试时要能跳过重同步，才能改完会议时间直接验证状态机。
    """
    synced = sync_calendar() if resync else 0
    now_iso = utc_now_iso()
    detail: list[str] = []
    for device in store.list_all_devices():
        for item in evaluate_device(device, now_iso):
            detail.append(f"{device.device_id} → {item}")
    expire_materials()               # F4.8：到期专属素材清理（服务端 + 通知设备）
    ensure_upload_links()            # F2.4/F4.7：新会议 → 生成上传链接 + 邮件通知
    if detail:
        print(f"[scheduler] {datetime.now(UTC).strftime('%H:%M:%S')} 下发 {len(detail)} 条：{detail}")
    return {"synced": synced, "commands": len(detail), "detail": detail}


def start() -> AsyncIOScheduler:
    """启动后台调度器（lifespan 里调用）。

    得到的数据：
        无（间隔取 TICK_SEC）。

    要做的操作：
        建 AsyncIOScheduler，挂 interval 任务；
        启动时先跑一次 tick（demo 一开机就有指令可看）。

    返回：
        AsyncIOScheduler 实例（关停时用它 shutdown）。

    为什么：PRD §4.2 要求调度层按固定周期触发，且不阻塞 FastAPI 事件循环。
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", seconds=TICK_SEC, id="meetcast_tick", max_instances=1)
    scheduler.start()
    tick()
    _scheduler = scheduler
    print(f"[scheduler] 已启动，间隔 {TICK_SEC}s")
    return scheduler


def shutdown() -> None:
    """关停调度器（lifespan 收尾用）。

    要做的操作：
        有实例就 shutdown(wait=False)，并清空全局引用。

    返回：
        无。

    为什么：不关会留下未收尾的定时任务，uvicorn 重启时会打警告。
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

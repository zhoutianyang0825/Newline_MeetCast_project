"""设备端接口（Newline_MeetCast_API_Spec.md §二，与 PRD §4.4 协议一致）

2.1 POST /api/device/poll       长轮询取指令（hold 至有指令或 25s 超时）
2.2 POST /api/device/ack        指令回执
2.3 POST /api/device/heartbeat  心跳上报（30s 一次，只管在线判定）
2.4 GET  /api/device/profile    设备档案（我是谁 / 绑在哪 / 校时）
2.5 GET  /api/device/schedule   本会议室滚动窗口日程（标牌页"下一场"、日程条用）
2.6 GET  /api/device/materials  应缓存素材清单（预拉取与 LRU 的依据）
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query

from app.errors import (
    ApiError,
    CODE_COMMAND_NOT_FOUND,
    CODE_DEVICE_NOT_FOUND,
)
from app.files import quick_checksum
from app.response import ok
from app.schemas import (
    AckRequest,
    ApiResponse,
    DeviceMaterialsOut,
    DeviceProfileOut,
    DeviceScheduleOut,
    HeartbeatOut,
    HeartbeatRequest,
    MaterialEntryOut,
    PollCommandOut,
    PollRequest,
    ScheduleItemOut,
)
from app.security import auth_device
from app.store import Device, Material, Room, shift_minutes, store, utc_now_iso
from app.tz import local_time_range

# hold 上限 25s（规范建议值）；轮询间隔 0.5s（内存队列查得快，又不会空转）
POLL_HOLD_SEC = 25.0
POLL_TICK_SEC = 0.5

# 日程窗口：默认未来 24h；往前留 60 分钟，让"刚开始的会"仍然出现在列表里
SCHEDULE_LOOKBACK_MIN = 60

router = APIRouter(prefix="/api/device", tags=["device"])


def _room_of(device: Device) -> Room | None:
    """设备 → 它绑定的会议室行。

    得到的数据：
        device（认证依赖查出的设备行，room_id 可能为 None）。

    要做的操作：
        room_id 为空 → 返回 None（未绑定）；否则按 room_id 查 rooms 表。

    返回：
        Room 行（含 room_name / timezone）或 None。

    为什么：profile / schedule / materials 三个接口都要"先知道设备属于哪个会议室"，
            收口成一个函数，避免三处各写一遍空值判断。
    """
    if not device.room_id:
        return None
    return store.get_room(device.room_id)


def _active_meeting_ids(room_id: str, now_iso: str) -> set[str]:
    """该会议室"还没结束且未取消"的会议 id 集合。

    得到的数据：
        room_id（会议室）；now_iso（服务器当前 UTC）。

    要做的操作：
        取会议室全部会议，过滤掉 cancelled 和 end_time 已过的。

    返回：
        {"meeting_a3_01_0", "meeting_a3_01_1"}（可能为空集）

    为什么：专属素材的生命周期跟着会议走——会没开完，素材就该还在设备上；
            会一结束，素材进入过期回收（F4.8）。
    """
    rows = store.meetings_of_room(room_id)
    return {
        m.meeting_id for m in rows
        if m.status != "cancelled" and m.end_time_utc >= now_iso
    }


def _pick_materials(device: Device) -> list[tuple[Material, str]]:
    """算该设备当前应缓存的素材全集（公共 + 本会议室各会议的专属）。

    得到的数据：
        device（设备行，用来定位会议室）。

    要做的操作：
        t1 全量素材里挑 scope=public 且未过期的 → reason="public"；
        t2 若已绑定，再挑 scope=meeting 且所属会议仍活跃的 → reason="meeting:<id>"；
        t3 按 material_id 去重（公共素材优先保留）。

    返回：
        [(Material, "public"), (Material, "meeting:meeting_a3_01_0")]

    为什么：设备只认"清单"，不该自己拼规则；把选择逻辑放服务端，
            以后加"按标签下发""按容量上限裁剪"都只改这一处。
    """
    now_iso = utc_now_iso()
    picked: dict[str, tuple[Material, str]] = {}

    for material in store.all_materials():
        if material.scope != "public":
            continue
        if material.expire_at and material.expire_at < now_iso:
            continue
        picked[material.material_id] = (material, "public")

    room = _room_of(device)
    if room is not None:
        active = _active_meeting_ids(room.room_id, now_iso)
        for material in store.all_materials():
            if material.scope != "meeting" or material.meeting_id not in active:
                continue
            if material.expire_at and material.expire_at < now_iso:
                continue
            picked.setdefault(material.material_id, (material, f"meeting:{material.meeting_id}"))

    return list(picked.values())



# ============ 2.1 长轮询取指令 ============

@router.post("/poll", response_model=ApiResponse)
async def poll(req: PollRequest, device: Device = Depends(auth_device)) -> ApiResponse:
    """长轮询取指令：hold 至有指令立即返回，25s 超时返回空。

    得到的数据：
        req（device_id 如 "SH-A3-01-01"，agent_version 如 "1.0.0"）；
        device（认证依赖查出的设备行）。

    要做的操作：
        校验 device_id 与密钥是同一台设备，不是 → 2001；
        刷新 agent_version / last_heartbeat（poll 也算存活信号）；
        25s 内每 0.5s 查一次队列：取到 PENDING → 标 SENT 立即返回；
        到点仍无 → 返回 command_id=None，设备立即重连。

    返回：
        有指令：{"command_id": "cmd_9f3a...", "type": "PREPARE_MEETING",
                 "payload": {...}, "initiated_by": "system", "checksum": "sha256:..."}
        无指令：{"command_id": null, "type": null, "payload": null,
                 "initiated_by": null, "checksum": null}

    为什么：设备不开端口、服务器不主动连，靠设备长轮询拉指令（PRD §4.4）；
            超时空返回 + 立即重连，实现"指令入队到设备取走 ≤5 秒"。
    """
    # 设备密钥和 device_id 必须是同一台设备（防止拿 A 的密钥替 B 拉指令）
    if req.device_id != device.device_id:
        raise ApiError(CODE_DEVICE_NOT_FOUND)
    # poll 也算存活信号，顺带刷新版本号（落库收口，F1.3）
    store.touch_device(device.device_id, agent_version=req.agent_version)
    device = store.get_device(device.device_id) or device

    loop = asyncio.get_running_loop()
    deadline = loop.time() + POLL_HOLD_SEC
    while True:
        command = store.pop_pending_command(device.device_id)
        if command is not None:
            # 有指令：立即返回（规范：指令入队到设备取走 ≤5 秒）
            return ok(PollCommandOut(
                command_id=command.command_id,
                type=command.type,
                payload=command.payload,
                initiated_by=command.initiated_by,
                checksum=command.checksum,
            ).model_dump())
        remaining = deadline - loop.time()
        if remaining <= 0:
            # 超时无指令：返回空，设备端立即重连（PRD §4.4）
            return ok(PollCommandOut(command_id=None).model_dump())
        # 让出事件循环 0.5s，不阻塞 heartbeat 等其他请求
        await asyncio.sleep(min(POLL_TICK_SEC, remaining))


# ============ 2.2 指令回执 ============

@router.post("/ack", response_model=ApiResponse)
async def ack(req: AckRequest, device: Device = Depends(auth_device)) -> ApiResponse:
    """指令回执：设备执行完指令后回报结果。

    得到的数据：
        req（command_id 如 "cmd_9f3a..."，status 只许 SUCCESS/FAILED，device_state 可选）；
        device（设备行）。

    要做的操作：
        command_id 不存在 → 2004；
        回执设备与指令归属不一致 → 2004（防 A 设备替 B 回执）；
        通过 → command 置 ACKED/FAILED 并记 acked_at，device_state 同步设备行。

    返回：
        {"code": 0, "message": "ok", "data": null}

    为什么：每条指令必须有终态和回执时间，审计与重试判定都靠它（F7.1/F7.2）。
    """
    command = store.ack_command(req.command_id, req.status, req.device_state)
    if command is None:
        # 规范 §2.2：command_id 不存在 → 2004
        raise ApiError(CODE_COMMAND_NOT_FOUND)
    # 防止 A 设备给 B 设备的指令回执（越权）
    if command.device_id != device.device_id:
        raise ApiError(CODE_COMMAND_NOT_FOUND)
    return ok(None)


# ============ 2.3 心跳上报 ============

@router.post("/heartbeat", response_model=ApiResponse)
async def heartbeat(req: HeartbeatRequest, device: Device = Depends(auth_device)) -> ApiResponse:
    """心跳上报：30s 一次的在线判定与状态采集。

    得到的数据：
        req（device_id；device_state 如 "IDLE"；playing / storage_used_mb 可选）；
        device（设备行）。

    要做的操作：
        device_id 与密钥不是同一台设备 → 2001；
        调 mark_heartbeat 刷新在线状态与采集字段；
        取服务器当前 UTC 时间返回。

    返回：
        {"server_time_utc": "2026-10-27T04:26:12Z"}

    为什么：返回校时时间——switch_at 定时切屏依赖设备本地时钟准确；
            离线判定不在本接口做，由 main.py 后台任务扫（90s 无心跳 → offline）。
    """
    if req.device_id != device.device_id:
        raise ApiError(CODE_DEVICE_NOT_FOUND)
    store.mark_heartbeat(
        device_id=req.device_id,
        device_state=req.device_state,
        playing=req.playing,
        storage_used_mb=req.storage_used_mb,
    )
    return ok(HeartbeatOut(server_time_utc=utc_now_iso()).model_dump())


# ============ 2.4 设备档案 ============

@router.get("/profile", response_model=ApiResponse)
def profile(device: Device = Depends(auth_device)) -> ApiResponse:
    """设备档案：开机自检——我是谁、绑在哪个会议室、服务器几点。

    得到的数据：
        device（认证依赖按 X-Device-Key 查出的设备行）。

    要做的操作：
        按 room_id 查会议室，拿到 room_name 与 timezone；
        未绑定 → bound=false、room 字段置 null（设备显示"未绑定"页）；
        回填服务器 UTC 时间供校时。

    返回：
        {"device_id": "SH-A3-01-01", "bound": true, "room_id": "room-a3-01",
         "room_name": "上海 A3-01", "timezone": "Asia/Shanghai", "server_time_utc": "..."}

    为什么：设备端 P0 的"绑定注册"发生在服务端（管理端 bind），设备侧要做的是
            "开机问一句：我现在绑没绑、绑在哪"——这个接口就是那一问。
    """
    room = _room_of(device)
    return ok(DeviceProfileOut(
        device_id=device.device_id,
        device_name=device.device_name,
        bound=room is not None,
        room_id=room.room_id if room else None,
        room_name=room.room_name if room else None,
        timezone=room.timezone if room else "Asia/Shanghai",
        server_time_utc=utc_now_iso(),
        agent_version=device.agent_version or "0.0.0",
    ).model_dump())


# ============ 2.5 会议室日程 ============

@router.get("/schedule", response_model=ApiResponse)
def schedule(
    hours: int = Query(24, ge=1, le=168, description="往后看多少小时（1~168）"),
    device: Device = Depends(auth_device),
) -> ApiResponse:
    """本会议室滚动窗口日程：设备渲染标牌"下一场"、日程条、预拉取目标都靠它。

    得到的数据：
        hours（往后看的小时数，默认 24）；
        device（设备行 → 会议室）。

    要做的操作：
        未绑定 → 直接返回空列表（bound=false）；
        取会议室会议，过滤 cancelled 与窗口外（往前留 60 分钟，让"刚开始的会"仍在列表）；
        按开始时间升序，标出 is_current（进行中）与 is_next（下一场）；
        标题过敏感词 → 换成"会议中"（与会议页口径一致，F5.5）；
        每场附 content_url，设备可提前拉取渲染页。

    返回：
        {"bound": true, "room_name": "上海 A3-01", "timezone": "Asia/Shanghai",
         "items": [{"meeting_id": "meeting_a3_01_0", "subject": "产品评审会",
                    "time_label": "10:08 – 11:08", "is_next": true, "content_url": "..."}]}

    为什么：会议页地址里的日历信息原本只能从 PREPARE_MEETING 指令拿，
            设备开机时是空白的；有了这个接口，标牌页能立刻显示"下一场 10:08 产品评审会"。
            device_id 不从 query 取——直接由密钥推出，杜绝"A 的密钥查 B 的日程"。
    """
    server_now = utc_now_iso()
    room = _room_of(device)
    if room is None:
        return ok(DeviceScheduleOut(
            device_id=device.device_id,
            bound=False,
            server_time_utc=server_now,
            window_hours=hours,
        ).model_dump())

    window_lo = shift_minutes(server_now, -SCHEDULE_LOOKBACK_MIN)
    window_hi = shift_minutes(server_now, hours * 60)
    rows = [
        m for m in store.meetings_of_room(room.room_id)
        if m.status != "cancelled" and m.end_time_utc >= window_lo and m.start_time_utc <= window_hi
    ]
    rows.sort(key=lambda m: m.start_time_utc)

    items: list[ScheduleItemOut] = []
    next_marked = False
    for meeting in rows:
        is_current = meeting.start_time_utc <= server_now <= meeting.end_time_utc
        is_next = False
        if not is_current and not next_marked and meeting.start_time_utc > server_now:
            is_next = True
            next_marked = True
        items.append(ScheduleItemOut(
            meeting_id=meeting.meeting_id,
            subject="会议中" if meeting.is_sensitive else meeting.subject,
            start_time_utc=meeting.start_time_utc,
            end_time_utc=meeting.end_time_utc,
            time_label=local_time_range(meeting.start_time_utc, meeting.end_time_utc, room.timezone),
            status=meeting.status,
            is_current=is_current,
            is_next=is_next,
            content_url=_content_url(meeting),
            is_sensitive=meeting.is_sensitive,
        ))

    return ok(DeviceScheduleOut(
        device_id=device.device_id,
        bound=True,
        room_id=room.room_id,
        room_name=room.room_name,
        timezone=room.timezone,
        window_hours=hours,
        server_time_utc=server_now,
        items=items,
    ).model_dump())


# ============ 2.6 应缓存素材清单 ============

@router.get("/materials", response_model=ApiResponse)
def materials(device: Device = Depends(auth_device)) -> ApiResponse:
    """该设备当前应缓存的素材全集（公共 + 本会议室各会议的专属）。

    得到的数据：
        device（设备行 → 会议室）。

    要做的操作：
        调 _pick_materials 选出全集（公共 + 活跃会议的专属，均已排除过期）；
        逐条补 checksum（预拉取后校验完整性）、expire_at（设备本地到期清理依据）、reason（排查用）；
        汇总 total_mb / count，供设备与后台展示占用。

    返回：
        {"bound": true, "total_mb": 2.4, "count": 1,
         "items": [{"material_id": "mat_001", "url": "http://.../media/mat_001.png",
                    "checksum": "sha256:...", "reason": "public"}]}

    为什么：设备端的"预拉取"必须有一份权威清单——哪些要、多大、下来后对不对、
            什么时候该删。缺了它，设备只能瞎猜，LRU 与离线播放都无从谈起。
    """
    server_now = utc_now_iso()
    picked = _pick_materials(device)

    items: list[MaterialEntryOut] = []
    total_mb = 0.0
    for material, reason in picked:
        total_mb += material.size_mb
        items.append(MaterialEntryOut(
            material_id=material.material_id,
            name=material.name,
            format=material.format,
            size_mb=material.size_mb,
            url=material.url,
            checksum=quick_checksum(material.file_path),
            scope=material.scope,
            meeting_id=material.meeting_id,
            expire_at=material.expire_at,
            reason=reason,
        ))

    room = _room_of(device)
    return ok(DeviceMaterialsOut(
        device_id=device.device_id,
        bound=room is not None,
        room_id=room.room_id if room else None,
        total_mb=round(total_mb, 2),
        count=len(items),
        server_time_utc=server_now,
        items=items,
    ).model_dump())


def _content_url(meeting) -> str:
    """会议渲染页地址（迟导入，避免 routers ↔ scheduler 在模块加载期互相牵连）。

    得到的数据：
        meeting（Meeting 行）。

    要做的操作：
        延迟 import scheduler.content_url_of，传会议行拿 URL。

    返回：
        "http://localhost:8000/ui/display/meeting.html?meeting_id=...&subject=..."

    为什么：content_url 的拼装规则（含敏感词脱敏、版式选择）只有 scheduler 一处实现，
            这里必须复用而不是复制，否则两个入口迟早给出不同 URL。
    """
    from app.scheduler import content_url_of

    return content_url_of(meeting)

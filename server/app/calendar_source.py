"""Graph Mock：假 M365 日历源（PRD §六「Mock 兜底」）

开发期拿不到真实 M365 账户（PRD 测试范围约束），用 fixture 顶替
Microsoft Graph calendarView 的返回结构，覆盖：
  跨时区（上海 / 巴塞罗那 / 纽约）、欧盟 DST、会议已进行中、已取消会议。

时间口径：fixture 一律以「当前时刻」为基准生成 UTC 时间，
存储与指令下发都用 UTC，时区只在渲染层按 IANA 名本地化 —— 这样 DST 切换
不需要任何手工偏移，是 F2.5「存储 UTC + 展示本地化」的实现落点。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.settings import FIRST_MEETING_MIN, MEETING_LEN_MIN

# ★ 锚点：fixture 的时间以"进程启动时刻"为基准，只算一次。
#   若每次 tick 都用 now 重新算，会议会一直往后滑，永远等不到开始/结束。
ANCHOR = datetime.now(UTC)

# 各房间的日程偏移（分钟）：负数=已开始，正数=未来
FIXTURE_OFFSETS_MIN = {
    "room-a3-01": [FIRST_MEETING_MIN, 95],   # 首场很快开、第二场 95 分钟后
    "room-b2-05": [-20],            # 已经开会 20 分钟（跳过 prepare，只等会后 REPLAY）
    "room-bcn-01": [240],           # 巴塞罗那，欧盟 DST 时区
    "room-ny-01": [300],            # 纽约，美式 DST 时区（本场 fixture 为已取消）
}


def reanchor(now: datetime | None = None) -> None:
    """重置 fixture 锚点（demo 重播/测试用）。

    得到的数据：
        now（新的基准时刻，默认当前 UTC）。

    要做的操作：
        覆盖模块级 ANCHOR。

    返回：
        无。

    为什么：服务跑久了首场会早已结束，重播演示时把锚点拉回现在即可重新演一遍。
    """
    global ANCHOR
    ANCHOR = now or datetime.now(UTC)


def _iso(moment: datetime) -> str:
    """datetime → UTC ISO 8601 字符串（规范：时间一律 UTC）。

    得到的数据：
        moment（带时区的 datetime，如 2026-10-27 10:00+00:00）。

    要做的操作：
        转 UTC 后格式化，秒级精度带 Z。

    返回：
        "2026-10-27T10:00:00Z"

    为什么：payload 与库表都只存 UTC，统一在这里出口，避免各处格式漂移。
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_events(now: datetime | None = None) -> list[dict]:
    """生成 fixture 日程（模拟 Graph calendarView 返回）。

    得到的数据：
        now（基准时刻；不传则用进程启动时锚定的 ANCHOR，保证每次拉取是同一批会）。

    要做的操作：
        按 FIXTURE_OFFSETS_MIN 的偏移为每间会议室生成会议；
        给每场会配标题、组织者、时区、状态（纽约那场置 cancelled）。

    返回：
        [{"meeting_id": "meeting_a3_01_0", "room_id": "room-a3-01", "subject": "产品评审会",
          "organizer_email": "zhangsan@honghe.com", "start_time_utc": "2026-10-27T10:08:00Z",
          "end_time_utc": "...", "timezone": "Asia/Shanghai", "status": "scheduled"}, ...]

    为什么：调度器要有一份"像真日历"的数据源，才能在无 M365 环境下验证 F2/F3 全链路。
    """
    base = now or ANCHOR
    titles = {
        "room-a3-01": ["产品评审会", "Q4 预算沟通"],
        "room-b2-05": ["周例会"],
        "room-bcn-01": ["Global Sales Sync"],
        "room-ny-01": ["Investor Update（已取消）"],
    }
    organizers = {
        "room-a3-01": "zhangsan@honghe.com",
        "room-b2-05": "lisi@honghe.com",
        "room-bcn-01": "anna@honghe.com",
        "room-ny-01": "mike@honghe.com",
    }
    timezones = {
        "room-a3-01": "Asia/Shanghai",
        "room-b2-05": "Asia/Shanghai",
        "room-bcn-01": "Europe/Madrid",
        "room-ny-01": "America/New_York",
    }
    # 参会人 fixture：会议页展示用（真实环境从 Graph attendees 取）
    attendee_pools = {
        "room-a3-01": ["张三", "李四", "王五", "赵六", "钱七", "孙八"],
        "room-b2-05": ["周九", "吴十", "郑一"],
        "room-bcn-01": ["Anna", "Marc", "Lucia", "Pau"],
        "room-ny-01": ["Mike", "Sara", "Tom"],
    }

    events: list[dict] = []
    for room_id, offsets in FIXTURE_OFFSETS_MIN.items():
        for index, offset in enumerate(offsets):
            start = base + timedelta(minutes=offset)
            end = start + timedelta(minutes=MEETING_LEN_MIN)
            # 会议 id 稳定可复现：room + 序号，保证每次 tick 是"同一场会"（去重靠它）
            meeting_id = f"meeting_{room_id.replace('room-', '').replace('-', '_')}_{index}"
            events.append({
                "meeting_id": meeting_id,
                "room_id": room_id,
                "subject": titles[room_id][index],
                "organizer_email": organizers[room_id],
                "attendees": attendee_pools[room_id],
                "start_time_utc": _iso(start),
                "end_time_utc": _iso(end),
                "timezone": timezones[room_id],
                "status": "cancelled" if room_id == "room-ny-01" else "scheduled",
            })
    return events

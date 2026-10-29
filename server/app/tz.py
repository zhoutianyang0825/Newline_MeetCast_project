"""时区与夏令时换算（F2.5）

原则：**存储一律 UTC，展示按 IANA 时区本地化**。
换算全部交给标准库 zoneinfo（内含 tzdata 规则），不做手工时差加减——
美欧 DST 切换日不同（美国 3 月第二个周日 / 11 月第一个周日；欧盟 3 月最后周日 /
10 月最后周日），手工算必错。
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def parse_utc(iso_text: str) -> datetime:
    """UTC ISO 字符串 → 带时区的 datetime。

    得到的数据：
        iso_text（形如 "2026-10-27T02:00:00Z"）。

    要做的操作：
        strptime 解析后挂 UTC 时区。

    返回：
        datetime(2026, 10, 27, 2, 0, tzinfo=UTC)

    为什么：后续换算必须拿到"带时区"的对象，裸 datetime 会被当成本地时间误算。
    """
    return datetime.strptime(iso_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def to_local(iso_text: str, tz_name: str) -> datetime:
    """UTC 时间串 → 指定 IANA 时区的本地时间。

    得到的数据：
        iso_text（UTC 串，如 "2026-10-27T02:00:00Z"）；
        tz_name（IANA 名，如 "Europe/Madrid"）。

    要做的操作：
        解析 UTC → astimezone(ZoneInfo(tz_name))。

    返回：
        datetime(2026, 10, 27, 3, 0, tzinfo=Europe/Madrid)（举例：CET 为 +1）

    为什么：DST 判断交给 tzdata，切换日自动用 +1/+2 的正确偏移。
    """
    return parse_utc(iso_text).astimezone(ZoneInfo(tz_name))


def local_hm(iso_text: str, tz_name: str) -> str:
    """UTC 时间串 → 本地 "HH:MM"（会议页直接显示）。

    得到的数据：
        iso_text（UTC 串）；tz_name（IANA 名）。

    要做的操作：
        换成本地时间后取时分，补零。

    返回：
        "10:00"（Asia/Shanghai 时区下的 02:00Z）

    为什么：页面只需要"几点到几点"，不需要带日期与时区后缀。
    """
    local = to_local(iso_text, tz_name)
    return f"{local.hour:02d}:{local.minute:02d}"


def local_time_range(start_utc: str, end_utc: str, tz_name: str) -> str:
    """会议本地时间段。

    得到的数据：
        start_utc / end_utc（UTC 串）；tz_name（会议室 IANA 时区）。

    要做的操作：
        两端各自换算成本地时分，用 " – " 连接。

    返回：
        "10:00 – 11:00"

    为什么：会议页与通知文案都以会议室本地时间为准，不是服务器时间也不是观众时间。
    """
    return f"{local_hm(start_utc, tz_name)} – {local_hm(end_utc, tz_name)}"


def utc_offset_label(iso_text: str, tz_name: str) -> str:
    """该时刻在目标时区的 UTC 偏移标签（排查 DST 用）。

    得到的数据：
        iso_text（UTC 串）；tz_name（IANA 名）。

    要做的操作：
        取本地时间的 utcoffset，格式化成 "+08:00"。

    返回：
        "+08:00" / "+01:00" / "+02:00"（欧盟冬/夏令时）

    为什么：DST 出问题时，第一眼要看的就是"这一刻服务器算成了哪个偏移"。
    """
    offset = to_local(iso_text, tz_name).utcoffset() or UTC.utcoffset(None)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"

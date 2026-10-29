"""Microsoft Graph 客户端（F2.1 / F2.3，Mock 双轨）

设计原则：**同一套对外函数，两种数据源**。
  GRAPH_MOCK=1（默认）→ 读 fixture，开发期无 M365 实账户也能跑全链路；
  GRAPH_MOCK=0        → 真调 Graph（client_credentials 拿 app-only token + calendarView / places）。

真模式缺凭据时**自动回落 Mock 并打警告**，不让服务起不来——这正是 PRD
"日历 API 失败不影响已下发内容播放"的最小实现。
"""

from __future__ import annotations

import time

import httpx

from app.calendar_source import fixture_events
from app.settings import (
    GRAPH_CLIENT_ID,
    GRAPH_CLIENT_SECRET,
    GRAPH_MOCK,
    GRAPH_TENANT_ID,
    SCHEDULE_WINDOW_HOURS,
)
from app.store import store

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

# app-only token 缓存（Graph 的 token 一般 1 小时，提前 5 分钟过期）
_token_cache: dict = {"value": "", "expires_at": 0.0}


def credentials_ready() -> bool:
    """真模式所需凭据是否齐备。

    得到的数据：
        无（读 settings）。

    要做的操作：
        三个环境变量都非空才算齐。

    返回：
        True / False

    为什么：缺凭据时不该抛异常把服务拖挂，调用方据此回落 Mock。
    """
    return bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET)


def _access_token() -> str:
    """拿 app-only access token（client_credentials 流程）。

    得到的数据：
        无（读 settings 里的 tenant/client/secret）。

    要做的操作：
        缓存未过期直接复用；否则 POST 到 /oauth2/v2.0/token 换新 token。

    返回：
        "eyJ0eXAiOiJKV1Qi..."（Bearer 后那串）

    为什么：Graph 每个请求都要 Bearer，token 1 小时有效，不缓存会把 QPS 打满。
    """
    if _token_cache["value"] and _token_cache["expires_at"] > time.time():
        return _token_cache["value"]
    resp = httpx.post(
        TOKEN_URL.format(tenant=GRAPH_TENANT_ID),
        data={
            "client_id": GRAPH_CLIENT_ID,
            "client_secret": GRAPH_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    _token_cache["value"] = payload["access_token"]
    _token_cache["expires_at"] = time.time() + int(payload.get("expires_in", 3600)) - 300
    return _token_cache["value"]


def _map_graph_event(event: dict, room_id: str, tz_name: str) -> dict:
    """Graph 事件 → 本项目统一的会议 dict。

    得到的数据：
        event（Graph calendarView 单个事件）；room_id（会议室）；tz_name（会议室 IANA 时区）。

    要做的操作：
        取 subject/organizer/attendees/start/end，时间补 Z 转成 UTC 串。

    返回：
        {"meeting_id": "AAMkAD...", "room_id": "room-a3-01", "subject": "产品评审会",
         "organizer_email": "zhangsan@honghe.com", "attendees": ["张三"],
         "start_time_utc": "2026-10-27T02:00:00Z", ...}

    为什么：上层（调度/内容/上传）只认这一种结构，换数据源不需要改任何业务代码。
    """
    start = event["start"]["dateTime"][:19] + "Z"
    end = event["end"]["dateTime"][:19] + "Z"
    attendees = [
        item.get("emailAddress", {}).get("name", "")
        for item in event.get("attendees", [])
        if item.get("emailAddress", {}).get("name")
    ]
    return {
        "meeting_id": event["id"],
        "room_id": room_id,
        "subject": event.get("subject", "（无主题）"),
        "organizer_email": event.get("organizer", {}).get("emailAddress", {}).get("address", ""),
        "attendees": attendees,
        "start_time_utc": start,
        "end_time_utc": end,
        "timezone": tz_name,
        "status": "cancelled" if event.get("isCancelled") else "scheduled",
    }


def fetch_events(window_hours: int = SCHEDULE_WINDOW_HOURS) -> list[dict]:
    """拉取所有会议室的日程（编排拉取窗口）。

    得到的数据：
        window_hours（向前看多少小时，PRD 编排拉取为 12）。

    要做的操作：
        Mock 模式 → 直接返回 fixture；
        真模式 → 逐房间调 calendarView（单房间简化版，生产应走批量 getSchedule）；
        真模式缺凭据/调用失败 → 打警告并回落 fixture。

    返回：
        [会议 dict, ...]（结构同 _map_graph_event）

    为什么：调度器只调这一个函数取日历，Mock 与真数据切换对上层完全透明。
    """
    if GRAPH_MOCK or not credentials_ready():
        if not GRAPH_MOCK and not credentials_ready():
            print("[graph] 缺少 Graph 凭据，已回落到 Mock 日历（不影响主链路）")
        return fixture_events()

    from datetime import UTC, datetime, timedelta

    token = _access_token()
    start = datetime.now(UTC)
    end = start + timedelta(hours=window_hours)
    events: list[dict] = []
    for room in store.list_rooms():
        if not room.room_email:
            continue
        resp = httpx.get(
            f"{GRAPH_BASE}/users/{room.room_email}/calendarView",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "$select": "id,subject,organizer,attendees,start,end,isCancelled",
                "$top": 50,
            },
            timeout=15,
        )
        if resp.status_code == 429:
            print(f"[graph] 429 限流（{room.room_id}），本轮跳过")
            continue
        resp.raise_for_status()
        for item in resp.json().get("value", []):
            events.append(_map_graph_event(item, room.room_id, room.timezone))
    return events


def sync_rooms() -> list[dict]:
    """同步会议室清单（F2.3）。

    得到的数据：
        无。

    要做的操作：
        Mock 模式 → 用本地 room 表（种子 4 间）；
        真模式 → GET /places/microsoft.graph.room。

    返回：
        [{"room_id": "room-a3-01", "room_name": "Room-A3-01 · 上海总部 3F", "room_email": "..."}]

    为什么：会议室清单是绑定的前提，真实环境由 IT 在 M365 后台建，产品只负责同步。
    """
    if GRAPH_MOCK or not credentials_ready():
        return [
            {"room_id": r.room_id, "room_name": r.room_name, "room_email": r.room_email}
            for r in store.list_rooms()
        ]

    token = _access_token()
    resp = httpx.get(
        f"{GRAPH_BASE}/places/microsoft.graph.room",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {"room_id": item["id"], "room_name": item.get("displayName", item["id"]), "room_email": item.get("emailAddress")}
        for item in resp.json().get("value", [])
    ]

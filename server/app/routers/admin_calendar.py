"""管理端 · 日历源 3 接口（Newline_MeetCast_API_Spec.md §六，JWT）

6.1 GET  /api/admin/calendar/config   读取配置（F2）
6.2 PUT  /api/admin/calendar/config   保存配置
6.3 POST /api/admin/calendar/test     连接测试（F2.7）

开发期无真实 M365 账户（PRD §六 测试范围约束），测试接口按配置状态与
环境变量 MEETCAST_CALENDAR_FAULT（expired / rate_limited）模拟 3001 / 3002。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.errors import ApiError, CODE_CALENDAR_CRED_INVALID, CODE_CALENDAR_RATE_LIMITED
from app.response import ok
from app.schemas import CalendarConfigIn, CalendarTestOut
from app.security import auth_admin
from app.settings import CALENDAR_FAULT
from app.store import store, utc_now_iso

router = APIRouter(prefix="/api/admin/calendar", tags=["admin-calendar"])


# ============ 6.1 读取配置 ============

@router.get("/config")
def get_config(_admin_id: str = Depends(auth_admin)) -> dict:
    """读取日历源配置（F2）。

    得到的数据：
        无（配置是单例）。

    要做的操作：
        把 CalendarConfig 逐字段摊平返回。

    返回：
        {"provider": "m365", "tenant": "honghe.onmicrosoft.com",
         "service_account": "svc-meetcast@honghe.com", "scopes": ["Calendars.Read", "Mail.Send"],
         "connection_status": "connected", "credential_expire_at": "2027-01-04T00:00:00Z",
         "pull_policy": {"schedule": {...}, "link_gen": {...}, "dst_enabled": true},
         "alert_email": "it-admin@honghe.com"}

    为什么：后台配置页要一眼看到"连着没有、凭证什么时候到期、多久拉一次"。
    """
    cfg = store.calendar_config
    return ok({
        "provider": cfg.provider,
        "tenant": cfg.tenant,
        "service_account": cfg.service_account,
        "scopes": cfg.scopes,
        "connection_status": cfg.connection_status,
        "credential_expire_at": cfg.credential_expire_at,
        "pull_policy": cfg.pull_policy,
        "alert_email": cfg.alert_email,
    })


# ============ 6.2 保存配置 ============

@router.put("/config")
def save_config(req: CalendarConfigIn, admin_id: str = Depends(auth_admin)) -> dict:
    """保存日历源配置。

    得到的数据：
        req（provider/tenant/service_account/pull_policy/alert_email；scopes 传了也不生效）。

    要做的操作：
        白名单字段覆盖写；
        scopes 保持服务端固定值（最小权限：只有 Calendars.Read + Mail.Send）；
        只读字段 connection_status / credential_expire_at 不碰。

    返回：
        {"code": 0, "message": "ok", "data": null}

    为什么：前端只能改开关/周期/告警邮箱，权限范围一旦放开就有越权读写的风险（规范 §6.2 备注）。
    """
    store.save_calendar_config(
        provider=req.provider,
        tenant=req.tenant,
        service_account=req.service_account,
        pull_policy=req.pull_policy.model_dump(),
        alert_email=req.alert_email,
    )
    # scopes 服务端固定：入参带了也忽略，维持最小权限
    print(f"[calendar] config saved by admin:{admin_id} alert_email={req.alert_email}")
    return ok(None)


# ============ 6.3 连接测试 ============

@router.post("/test")
def test_connection(_admin_id: str = Depends(auth_admin)) -> dict:
    """连接测试（F2.7）。

    得到的数据：
        无入参；异常场景由环境变量 MEETCAST_CALENDAR_FAULT 注入（expired / rate_limited）。

    要做的操作：
        先看故障开关（settings.CALENDAR_FAULT）→ 3001 凭证失效 / 3002 限流；
        否则真算一次调用耗时（ms），统计已同步会议室数。

    返回：
        {"auth_ok": true, "rooms_synced": 4, "api_latency_ms": 3, "checked_at": "2026-10-27T09:10:00Z"}

    为什么：真 M365 联调在 M6，开发期要能验证"测试按钮"的两条失败分支（3001/3002）与成功分支。
    """
    if CALENDAR_FAULT == "expired":
        raise ApiError(CODE_CALENDAR_CRED_INVALID)
    if CALENDAR_FAULT == "rate_limited":
        raise ApiError(CODE_CALENDAR_RATE_LIMITED)

    started = time.perf_counter()
    rooms_synced = store.count_rooms()
    latency_ms = int((time.perf_counter() - started) * 1000)
    return ok(CalendarTestOut(
        auth_ok=True,
        rooms_synced=rooms_synced,
        api_latency_ms=latency_ms,
        checked_at=utc_now_iso(),
    ).model_dump())

"""管理端 · 运维 2 接口（Newline_MeetCast_API_Spec.md §七，JWT）

7.1 GET  /api/admin/commands          指令审计记录（F7.1 / F8.3）
7.2 POST /api/admin/commands/switch   手动干预切换（F7.5，唯一允许人工触发 SWITCH_CONTENT 的入口）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.errors import (
    ApiError,
    CODE_DEVICE_NOT_FOUND,
    CODE_DEVICE_OFFLINE,
    MESSAGES,
)
from app.response import ok
from app.schemas import CommandItem, SwitchOut, SwitchRequest
from app.security import auth_admin
from app.store import store

router = APIRouter(prefix="/api/admin/commands", tags=["admin-commands"])


# ============ 7.1 指令审计 ============

@router.get("")
def list_commands(
    device_id: str | None = Query(None, description="只看某台设备"),
    initiated_by: str | None = Query(None, description="如 system / admin:admin_001"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin_id: str = Depends(auth_admin),
) -> dict:
    """指令审计记录（F7.1 / F8.3）。

    得到的数据：
        device_id（可选过滤）；initiated_by（可选过滤，如 "admin:admin_001"）；page/page_size（分页）。

    要做的操作：
        调 store.list_commands 取本页（按 created_at 倒序），逐条转 CommandItem。

    返回：
        {"items": [{"command_id": "cmd_9f3a1b", "device_id": "SH-A3-01-01",
                    "type": "PREPARE_MEETING", "status": "ACKED",
                    "initiated_by": "system", "retry_count": 0, ...}], "total": 128}

    为什么：事后定位"这条指令是谁发的、什么时候 ACK 的"只有这份审计流能回答。
    """
    rows, total = store.list_commands(device_id=device_id, initiated_by=initiated_by, page=page, page_size=page_size)
    items = [
        CommandItem(
            command_id=c.command_id,
            device_id=c.device_id,
            type=c.type,
            status=c.status,
            initiated_by=c.initiated_by,
            created_at=c.created_at,
            acked_at=c.acked_at,
            retry_count=c.retry_count,
        ).model_dump()
        for c in rows
    ]
    return ok({"items": items, "total": total})


# ============ 7.2 手动干预切换 ============

@router.post("/switch")
def switch_content(req: SwitchRequest, admin_id: str = Depends(auth_admin)) -> dict:
    """手动切换设备内容（F7.5，如应急通知）。

    得到的数据：
        req（device_id + content_url + until）；admin_id（审计用，initiated_by=admin:<id>）。

    要做的操作：
        设备不存在 → 2001；
        入队 SWITCH_CONTENT（command_id 服务端生成，重试不重复下发）；
        设备离线 → 返回 2009，但命令已入队 PENDING，上线后经 poll 自动下发。

    返回：
        在线：{"code": 0, "message": "ok", "data": {"command_id": "cmd_a1b2c3"}}
        离线：{"code": 2009, "message": "设备离线，指令已入队", "data": {"command_id": "cmd_a1b2c3"}}

    为什么：自动切屏走 PREPARE_MEETING.switch_at，本接口只留给人工干预（唯一路径，避免双路径打架）；
            离线不阻塞是 PRD 硬要求——指令躺队列里等设备回来。
    """
    device = store.get_device(req.device_id)
    if device is None:
        raise ApiError(CODE_DEVICE_NOT_FOUND)
    room = store.get_room(device.room_id)
    command = store.enqueue_command(
        device_id=req.device_id,
        type_="SWITCH_CONTENT",
        payload={
            "content_url": req.content_url,
            "until": req.until,
            "timezone": room.timezone if room else "Asia/Shanghai",
        },
        initiated_by=f"admin:{admin_id}",
    )
    print(f"[switch] {req.device_id} → {req.content_url} by admin:{admin_id} cmd={command.command_id}")
    if device.status != "online":
        # 离线：命令已入队，用 2009 提示但把 command_id 一起给前端
        return {
            "code": CODE_DEVICE_OFFLINE,
            "message": MESSAGES[CODE_DEVICE_OFFLINE],
            "data": SwitchOut(command_id=command.command_id).model_dump(),
        }
    return ok(SwitchOut(command_id=command.command_id).model_dump())

"""管理端 · 设备 3 接口（Newline_MeetCast_API_Spec.md §三，JWT 管理员）

3.1 GET  /api/admin/devices          设备列表（F1.3）
3.2 POST /api/admin/devices/bind     绑定设备（F1.1 / 场景 B 终点）
3.3 POST /api/admin/devices/unbind   解绑（F1.4）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.errors import (
    ApiError,
    CODE_DEVICE_ALREADY_BOUND,
    CODE_DEVICE_NOT_FOUND,
    CODE_PARAM_INVALID,
    CODE_ROOM_BOUND_OTHER,
    CODE_ROOM_NOT_FOUND,
)
from app.response import ok
from app.schemas import BindOut, BindRequest, DeviceListItem, UnbindRequest
from app.security import auth_admin, auth_user
from app.store import Device, store, utc_now_iso

# 换绑后调度生效时长（秒），规范 §3.2 固定 300（F1 验收：5 分钟内生效）
BIND_EFFECTIVE_SEC = 300

router = APIRouter(prefix="/api/admin/devices", tags=["admin-devices"])


def _to_list_item(device: Device) -> DeviceListItem:
    """Device 行 → 列表条目（顺带把 room_id 翻译成 room_name）。

    得到的数据：
        device（store 里的 Device 行）。

    要做的操作：
        逐字段搬进 DeviceListItem；room_id 非空时去 rooms 查展示名。

    返回：
        DeviceListItem，如 {"device_id": "SH-A3-01-01", "room_name": "Room-A3-01 · 上海总部 3F", ...}

    为什么：列表返回格式以规范 §3.1 为准（Pydantic model 即文档），翻译逻辑只此一处。
    """
    room = store.get_room(device.room_id)
    return DeviceListItem(
        device_id=device.device_id,
        device_name=device.device_name,
        room_id=device.room_id,
        room_name=room.room_name if room else None,
        status=device.status,
        device_state=device.device_state,
        playing=device.playing,
        agent_version=device.agent_version,
        last_heartbeat=device.last_heartbeat,
        storage_used_mb=device.storage_used_mb,
    )


# ============ 3.1 设备列表 ============

@router.get("", response_model_exclude_none=False)
def list_devices(
    status: str | None = Query(None, description="online / offline，不传=全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user_id: str = Depends(auth_user),
) -> dict:
    """设备列表：展示全部设备的状态采集字段（F1.3）。

    得到的数据：
        status（可选过滤，"online"/"offline"）；page/page_size（分页，页码从 1 起）。

    要做的操作：
        status 传了但不是 online/offline → 1001；
        调 store.list_devices 分页取本页设备；
        逐台翻译成 DeviceListItem（room_id → room_name）。

    返回：
        {"items": [DeviceListItem...], "total": 12}，如
        {"items": [{"device_id": "SH-A3-01-01", "room_name": "Room-A3-01 · 上海总部 3F",
                    "status": "online", "device_state": "MEETING", ...}], "total": 2}

    为什么：后台设备管理页的数据源，在线状态/播放内容/APK 版本一眼可查（F1.3 验收）。
    """
    if status is not None and status not in ("online", "offline"):
        raise ApiError(CODE_PARAM_INVALID, "status 只允许 online / offline")
    devices, total = store.list_devices(status=status, page=page, page_size=page_size)
    return ok({"items": [_to_list_item(d).model_dump() for d in devices], "total": total})


# ============ 3.2 绑定设备 ============

@router.post("/bind")
def bind_device(req: BindRequest, admin_id: str = Depends(auth_admin)) -> dict:
    """绑定设备到会议室（F1.1 / 场景 B 终点）。

    得到的数据：
        req（device_id + room_id + force，force=true 才允许覆盖已有绑定）；
        admin_id（JWT 解出的管理员，审计用）。

    要做的操作：
        设备不存在 → 2001；会议室不存在 → 2003；
        设备已绑且未 force → 2002；会议室被其他设备占用且未 force → 2008；
        通过 → 写 device.room_id，记审计日志。

    返回：
        {"device_id": "SH-A3-01-01", "room_id": "room-a3-01",
         "bound_at": "2026-10-27T04:30:00Z", "effective_in_sec": 300}

    为什么：场景 B 的终点动作——绑完设备就纳入该会议室的调度范围（5 分钟内生效）。
    """
    if not store.device_exists(req.device_id):
        raise ApiError(CODE_DEVICE_NOT_FOUND)
    if not store.get_room(req.room_id):
        raise ApiError(CODE_ROOM_NOT_FOUND)
    target = store.get_device(req.device_id)
    # 设备已绑到别的会议室：force 才允许换绑（2002）
    if target.room_id is not None and target.room_id != req.room_id and not req.force:
        raise ApiError(CODE_DEVICE_ALREADY_BOUND)
    # 目标会议室已被其他设备占用：force 才允许抢占（2008）
    occupant = store.room_occupant(req.room_id)
    if occupant is not None and occupant != req.device_id and not req.force:
        raise ApiError(CODE_ROOM_BOUND_OTHER)
    store.bind_device(req.device_id, req.room_id)
    # 审计必埋（F8.3）：换绑是人工操作，initiated_by = admin:<user_id>
    print(f"[bind] {req.device_id} → {req.room_id} by admin:{admin_id} force={req.force}")
    return ok(BindOut(
        device_id=req.device_id,
        room_id=req.room_id,
        bound_at=utc_now_iso(),
        effective_in_sec=BIND_EFFECTIVE_SEC,
    ).model_dump())


# ============ 3.3 解绑 ============

@router.post("/unbind")
def unbind_device(req: UnbindRequest, admin_id: str = Depends(auth_admin)) -> dict:
    """解绑设备（F1.4）。

    得到的数据：
        req（device_id）；admin_id（管理员，审计用）。

    要做的操作：
        设备不存在 → 2001；
        通过 → device.room_id 置 None（重复解绑幂等，不报错）。

    返回：
        {"code": 0, "message": "ok", "data": null}

    为什么：换绑/注销前都要先解绑（F1.4），解绑后设备退出调度范围。
    """
    if not store.device_exists(req.device_id):
        raise ApiError(CODE_DEVICE_NOT_FOUND)
    store.unbind_device(req.device_id)
    print(f"[unbind] {req.device_id} by admin:{admin_id}")
    return ok(None)

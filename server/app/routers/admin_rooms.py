"""管理端 · 会议室（F1.1 扫码绑定入口 / F2.3 会议室清单）

1 个接口：
  GET /api/admin/rooms  会议室列表 + 每间房的可打印绑定二维码

为什么单独一个路由文件：
    会议室是独立资源（后面还要挂容量、设备占用、今日会议），
    塞进 admin_devices 会让"设备"与"房间"两个概念混在一起。
"""

from __future__ import annotations

import io

import qrcode
from qrcode.image.svg import SvgPathImage
from fastapi import APIRouter, Depends, Query

from app.response import ok
from app.security import auth_user
from app.settings import PUBLIC_BASE
from app.store import store, utc_now_iso

router = APIRouter(prefix="/api/admin/rooms", tags=["admin-rooms"])


def _qr_svg(payload: str) -> str:
    """把一段文本编码成 SVG 二维码。

    得到的数据：
        payload（二维码内容，如 "http://localhost:8000/ui/index.html?room_id=room-a3-01#devices"）。

    要做的操作：
        QRCode(box_size=6, border=2) → make(fit=True) → SvgPathImage → 转字符串。

    返回：
        "<svg ...>...</svg>" 文本（约 1~2KB）。

    为什么：用 SVG 而不是 PNG——无需 Pillow 依赖、任意倍数打印都清晰，
             贴在会议室门口用 A4 打印也不会糊。
    """
    qr = qrcode.QRCode(version=None, box_size=6, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def _bind_url(room_id: str) -> str:
    """会议室二维码里编码的落地地址。

    得到的数据：
        room_id（会议室 id，如 "room-a3-01"）。

    要做的操作：
        拼成后台"设备"页的地址，带上 room_id 锚点。

    返回：
        "http://localhost:8000/ui/index.html?room_id=room-a3-01#devices"

    为什么：扫码后必须直接落到"这台设备要绑到哪间房"的上下文里（PRD F1.1：
            二维码只含 room_id），管理员不用再手动选一次房间，少一个出错点。
    """
    return f"{PUBLIC_BASE}/ui/index.html?room_id={room_id}#devices"


@router.get("")
def list_rooms(
    include_qr: bool = Query(True, description="是否内联二维码 SVG（列表页展示用）"),
    _user_id: str = Depends(auth_user),
) -> dict:
    """会议室列表 + 绑定二维码（F1.1 / F2.3）。

    得到的数据：
        include_qr（默认 true；打印页/纯列表可关掉以减小响应体）。

    要做的操作：
        t1 遍历 store.rooms；
        t2 每间房补：占用设备（一台房一台屏）、今日会议数、日历状态；
        t3 生成绑定二维码 SVG 与 bind_url；
        t4 组装统一返回壳。

    返回：
        {"items": [{"room_id": "room-a3-01", "room_name": "Room-A3-01 · 上海总部 3F",
                    "occupant_device_id": "SH-A3-01-01", "today_meetings": 2,
                    "calendar_status": "connected",
                    "bind_url": "http://localhost:8000/ui/index.html?room_id=...",
                    "qr_svg": "<svg .../>"}], "total": 4}

    为什么：这是"扫码绑定"链路的起点——二维码必须先有个权威来源，
            否则门口贴的码和后台对不上，绑定必然出错。
    """
    now = utc_now_iso()
    today = now[:10]
    provider = getattr(store.calendar_config, "provider", "") or ""
    calendar_status = "connected" if provider else "disconnected"

    items = []
    for room in store.list_rooms():
        meetings = [
            m for m in store.meetings_of_room(room.room_id)
            if m.status != "cancelled" and m.start_time_utc[:10] == today
        ]
        url = _bind_url(room.room_id)
        items.append({
            "room_id": room.room_id,
            "room_name": room.room_name,
            "room_email": room.room_email,
            "timezone": room.timezone,
            "occupant_device_id": store.room_occupant(room.room_id),
            "today_meetings": len(meetings),
            "calendar_status": calendar_status,
            "bind_url": url,
            "qr_svg": _qr_svg(url) if include_qr else None,
        })

    items.sort(key=lambda x: x["room_id"])
    return ok({"items": items, "total": len(items)})

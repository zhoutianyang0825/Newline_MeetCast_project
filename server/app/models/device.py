"""设备表：物理不删（评审决策 #3）——解绑置空 room_id，下线置 status=offline。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Device(Base):
    """设备表（物理不删：解绑置空 room_id，下线置 status=offline）。

    字段：device_id（主键）；device_key（认证凭据，UNIQUE）；device_name（展示名）；room_id（FK，NULL=未绑定）；status（online/offline）；device_state/playing/agent_version/storage_used_mb（心跳采集）；last_heartbeat（最近心跳）；created_at（建档时间）。
    """
    __tablename__ = "device"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_name: Mapped[str | None] = mapped_column(String(128))
    device_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    room_id: Mapped[str | None] = mapped_column(ForeignKey("room.room_id"))
    status: Mapped[str] = mapped_column(String(16), default="offline")
    device_state: Mapped[str | None] = mapped_column(String(16))
    playing: Mapped[str | None] = mapped_column(String(255))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    storage_used_mb: Mapped[float | None] = mapped_column(Float)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

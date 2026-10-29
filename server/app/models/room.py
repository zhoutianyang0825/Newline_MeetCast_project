"""会议室表：房间邮箱是 M365 轮询锚点，timezone 是 DST 正确性的根。"""

from datetime import datetime

from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Room(Base):
    """会议室表。

    字段：room_id（主键）；room_name（后台展示名）；room_email（M365 房间邮箱，UNIQUE，轮询锚点）；building/floor/capacity（静态档案，可空）；timezone（IANA 时区，DST 换算依据）；created_at（建档时间）。
    """
    __tablename__ = "room"

    room_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    room_name: Mapped[str] = mapped_column(String(128))
    room_email: Mapped[str] = mapped_column(String(255), unique=True)
    building: Mapped[str | None] = mapped_column(String(128))
    floor: Mapped[str | None] = mapped_column(String(32))
    capacity: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

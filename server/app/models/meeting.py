"""会议表：PK = 日历事件 id，sync_calendar 每轮覆盖写（评审决策 #4）。

(room_id, start_time_utc) 复合索引服务状态机每 tick 按 room 扫会议的主路径。
is_sensitive 在同步时就判定落库，避免每次下发重复判定。
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Meeting(Base):
    """会议表（日历事件覆盖写缓存）。

    字段：meeting_id（主键=日历事件 id）；room_id（FK）；subject（标题）；organizer_email（定会者）；attendees（JSON 参会人）；start_time_utc/end_time_utc（起止 UTC）；timezone（渲染时区）；status（scheduled/cancelled/ended）；is_sensitive（同步时判定落库）；created_at/updated_at（覆盖写留痕）。
    """
    __tablename__ = "meeting"

    meeting_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("room.room_id"))
    subject: Mapped[str] = mapped_column(String(255))
    organizer_email: Mapped[str] = mapped_column(String(255))
    attendees: Mapped[list] = mapped_column(JSON, default=list)  # 参会人（会议页展示用）
    start_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_meeting_room_start", "room_id", "start_time_utc"),
    )

"""指令队列表：唯一事实源（Redis 只是加速层）。

command_id 幂等键；(device_id, status) 复合索引服务 poll 主查询路径。
payload 用跨库 JSON：PG 上是 JSONB，SQLite 单测退化 TEXT（评审决策 #2）。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Command(Base):
    """指令队列表（唯一事实源，Redis 只是加速层）。

    字段：command_id（主键=幂等键）；device_id（FK）；type（指令类型枚举）；payload（JSONB 参数）；status（PENDING→SENT→ACKED/FAILED/TIMEOUT）；initiated_by（审计必埋）；checksum（防篡改）；retry_count（重试计数）；created_at/sent_at/acked_at（三个时间点）。
    """
    __tablename__ = "command"

    command_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("device.device_id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    initiated_by: Mapped[str] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(80))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_command_device_status", "device_id", "status"),
    )

"""免登录上传凭据表：三重约束（绑 meeting_id / 会后失效 / max_uses）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UploadToken(Base):
    """免登录上传凭据表（F4.7，三重约束）。

    字段：token（主键=URL 随机串）；meeting_id（FK，绑定本场会）；organizer_email（审计归属）；expire_at（会后失效）；used_count/max_uses（防滥用计数）；revoked_at（撤销时刻）；created_at（签发时间）。
    """
    __tablename__ = "upload_token"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meeting.meeting_id"), index=True
    )
    organizer_email: Mapped[str] = mapped_column(String(255))
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=50)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

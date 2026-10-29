"""素材表：公共/专属双轨；物理删 + 双侧清理（评审决策 #5）。

last_used_at 是 15 天 LRU 的排序依据；expire_at 是到期清理扫描的依据——两列都要索引。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Material(Base):
    """素材表（公共/专属双轨，物理删 + 双侧清理）。

    字段：material_id（主键）；name/format/size_mb/url/file_path（文件本体）；scope（public/meeting）；meeting_id（FK，专属必填）；category（一级分类）；tags（JSON 自由标签）；uploaded_by（审计）；expire_at（到期清理依据，可索引）；last_used_at（15 天 LRU 依据，NULL=从未使用）；created_at（上传时间）。
    """
    __tablename__ = "material"

    material_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(8))
    url: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str | None] = mapped_column(String(512))
    size_mb: Mapped[float] = mapped_column(Float)
    scope: Mapped[str] = mapped_column(String(8))
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meeting.meeting_id"))
    category: Mapped[str] = mapped_column(String(16), default="other")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    uploaded_by: Mapped[str] = mapped_column(String(64))
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )  # NULL=从未被使用（LRU 排序时最旧）
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_material_scope_meeting", "scope", "meeting_id"),
    )

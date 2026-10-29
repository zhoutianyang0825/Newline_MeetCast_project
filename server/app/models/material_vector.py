"""素材向量元数据表（向量本体在 Milvus）。

评审决策 #6：1:1 附属表——有行 = 已向量化，无行 = 待补向量（2013 可重试的判定落点）。
material 删除时经 ondelete=CASCADE 清理元数据行（Milvus 向量由服务层另行删）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MaterialVector(Base):
    """素材向量元数据表（向量本体在 Milvus，本表 1:1 附属）。

    字段：material_id（主键+FK，ondelete=CASCADE）；milvus_pk（Milvus 主键，删向量时定位）；embedding_model（模型名，换模型时可定位重嵌）；embedded_at（向量化时间）。有行=已向量化，无行=待补（2013 可重试）。
    """
    __tablename__ = "material_vector"

    material_id: Mapped[str] = mapped_column(
        ForeignKey("material.material_id", ondelete="CASCADE"),
        primary_key=True,
    )
    milvus_pk: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(64))
    embedded_at: Mapped[datetime] = mapped_column(server_default=func.now())

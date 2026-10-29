"""品牌知识库文档表：status 状态机 parsing→embedding→ready / failed（可重试）。"""

from datetime import datetime

from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KbDocument(Base):
    """品牌知识库文档表（RAG 语料，F4.9）。

    字段：doc_id（主键）；title（标题）；source_uri（原始文件地址）；status（parsing/embedding/ready/failed 状态机）；chunk_count（分块数）；embedding_model（模型名）；uploaded_by（审计）；created_at（上传时间）。
    """
    __tablename__ = "kb_document"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="parsing")
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

"""后台账号表：role 走 String + 应用层 VALID_ROLES 校验（评审决策 #1，PrismEdu D3 同款）。"""

from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

VALID_ROLES = {"admin", "user"}


class AppUser(Base):
    """后台账号表（role 走 String + 应用层 VALID_ROLES 校验，PrismEdu D3 同款）。

    字段：user_id（主键）；email（登录名，UNIQUE）；name（展示名）；role（admin/user）；password_hash/salt（PBKDF2 派生值）；created_at（建档时间）。
    """
    __tablename__ = "app_user"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(128))
    salt: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

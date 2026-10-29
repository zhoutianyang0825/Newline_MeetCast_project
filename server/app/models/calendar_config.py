"""日历源配置表：单行表（id=1 恒定），运行时可改拉取周期/告警邮箱。

评审决策 #7：配置入库（改了不用重启），但凭据（tenant_id/client_id/secret）
永不入库——只存 .env，防"一个 SQL 注入拖走租户凭据"。
"""

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CalendarConfig(Base):
    """日历源配置表（单行表 id=1 恒定；凭据永不入库，只存 .env）。

    字段：id（恒为 1）；provider/tenant/service_account（接入身份展示）；pull_schedule_min/pull_link_gen_min/link_window_days（拉取周期与窗口）；dst_enabled（DST 开关）；alert_email（告警收件人）；updated_at（修改留痕）。
    """
    __tablename__ = "calendar_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(16), default="m365")
    tenant: Mapped[str | None] = mapped_column(String(255))
    service_account: Mapped[str | None] = mapped_column(String(255))
    pull_schedule_min: Mapped[int] = mapped_column(Integer, default=5)
    pull_link_gen_min: Mapped[int] = mapped_column(Integer, default=30)
    link_window_days: Mapped[int] = mapped_column(Integer, default=7)
    dst_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_email: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

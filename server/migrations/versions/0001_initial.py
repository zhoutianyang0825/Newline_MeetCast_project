"""0001_initial：首版迁移 = 模型即迁移（评审稿 §三 / PrismEdu D8 同款）

策略：不手写 10 张表 DDL，直接 Base.metadata.create_all()；
执行前检查库中已存在业务表则报错拒绝——防止 create_all 在旧库上"半途合并"。
边界：0002 起改用 autogenerate diff，手写只做微调。

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 业务表名单（与 models/__init__ 登记处一致）——空库校验用
_BUSINESS_TABLES = {
    "room", "device", "command", "meeting", "upload_token",
    "material", "material_vector", "kb_document", "app_user",
    "calendar_config",
}


def _existing_business_tables(inspector) -> set[str]:
    names = set(inspector.get_table_names())
    # alembic 自己的版本表不算业务表
    names.discard("alembic_version")
    return names & _BUSINESS_TABLES


def upgrade() -> None:
    """首版建表：create_all + 空库守卫。

    得到的数据：
        无（模型定义来自 app.models 的 Base.metadata）。

    要做的操作：
        检查库中已有业务表（有 → RuntimeError 拒绝）→ create_all 建全部 10 张表。

    返回：
        无。

    为什么：首版"模型即迁移"零漂移；空库校验防止 create_all 在旧库上半途合并。
    """
    from sqlalchemy import inspect

    from app.models import Base

    bind = op.get_bind()
    inspector = inspect(bind)
    existing = _existing_business_tables(inspector)
    if existing:
        raise RuntimeError(
            f"0001_initial 要求空库，但发现已存在的业务表：{sorted(existing)}。"
            "0001 只允许在全新库上执行；旧数据请走 0002+ 的 diff 迁移。"
        )
    # create_all 只建不存在的表，配合上面的空库校验 = "模型即迁移"零漂移
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """回滚首版：删除 0001 建出的全部业务表（含数据，不可逆）。

    得到的数据：
        无。

    要做的操作：
        找出现存业务表 → 按依赖拓扑 drop_all；库本来就空则无事可做。

    返回：
        无。

    为什么：downgrade 必须能回到"干净空库"，才是完整的可回滚迁移。
    """
    from sqlalchemy import inspect

    from app.models import Base

    bind = op.get_bind()
    inspector = inspect(bind)
    existing = _existing_business_tables(inspector)
    if not existing:
        return  # 空库，无事可做
    # drop_all 按依赖反序删（FK 依赖由 metadata 拓扑排序处理）
    Base.metadata.drop_all(bind=bind, tables=[
        Base.metadata.tables[t] for t in sorted(existing)
    ])

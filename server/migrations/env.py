"""Alembic 迁移环境：URL 与 metadata 全部接自应用配置（单一事实源）。

- sqlalchemy.url 取 app.settings.DATABASE_URL（.env 的 MEETCAST_DATABASE_URL / DATABASE_URL）
- target_metadata 接 Base（models/__init__ 已把全部模型串起来 import）
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.models import Base  # noqa: F401 —— import 副作用即"登记全部模型"
from app.settings import DATABASE_URL

config = context.config

# URL 以应用配置为准（alembic.ini 里的占位值不生效）
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 不连库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),  # SQLite 改列需 batch 模式
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url_is_sqlite(connection),
        )

        with context.begin_transaction():
            context.run_migrations()


def url_is_sqlite(connection) -> bool:
    return connection.dialect.name == "sqlite"


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

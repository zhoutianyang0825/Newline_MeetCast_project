"""冒烟脚本共用：一次性冒烟库（放 /tmp，见下）。

非 HTTP 冒烟直接调 store/scheduler，依赖"seed 后 fixture 锚定当前时刻"——
持久化后如果共用开发库，第二次跑就是旧锚点，用例必炸。
所以每套冒烟跑前切到一次性 SQLite 文件并清掉旧文件；必须在 import app.* 之前调用。

为什么放 /tmp 而不是项目 data/：WorkBuddy 工具沙箱会破坏项目目录下 SQLite
的文件锁（写操作报 disk I/O error），/tmp 不受影响——冒烟在沙箱内外都能跑。
HTTP 冒烟不受影响（走真实服务的库）。
"""

from __future__ import annotations

import os
from pathlib import Path

_SMOKOKE_DB_PATH = Path("/tmp/meetcast_smoke.db")


def use_fresh_smoke_db() -> None:
    """切到一次性冒烟库并清掉残留（幂等，可重复调用）。

    得到的数据：
        无（读 MEETCAST_DATABASE_URL：外部已指定则尊重，否则接管）。

    要做的操作：
        删掉 /tmp 旧库与 -journal 残留 → 设 env 指向新库 →
        create_all 建表（冒烟脚本不经服务 lifespan，建表在这里补）。

    返回：
        无。

    为什么：非 HTTP 冒烟依赖"seed 后 fixture 锚定当前时刻"，共用开发库
            第二次跑就是旧锚点，用例必炸；必须在 import app.* 之前调用。
    """
    if os.environ.get("MEETCAST_DATABASE_URL"):
        return  # 外部已指定（如 CI），尊重它
    for stale in (_SMOKOKE_DB_PATH, Path(str(_SMOKOKE_DB_PATH) + "-journal")):
        if stale.exists():
            stale.unlink()
    os.environ["MEETCAST_DATABASE_URL"] = f"sqlite:///{_SMOKOKE_DB_PATH}"

    # 冒烟脚本不经服务 lifespan，建表在这里补（幂等 create_all）
    from app.db.session import get_engine  # noqa: E402 —— 必须在 env 切换后 import
    from app.models import Base  # noqa: E402

    Base.metadata.create_all(bind=get_engine())

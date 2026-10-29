"""Base 登记制（评审稿 D 决策 #7 / PrismEdu D7 同款）

所有模型必须 import 此 Base——Base.metadata 是建表与 Alembic 迁移的唯一数据源。
漏 import 的模型是"幽灵表"：create_all 和 Alembic 都看不见它。

1) DeclarativeBase —— "声明式基类"基座
   是啥：SQLAlchemy 2.0 的官方基类。继承它写一个空类，这个类就自带两样东西：
        ① registry（登记处）：所有继承 Base 的模型类自动注册进来；
        ② metadata（表结构清单）：登记时把"表名/列名/类型/索引"全记到 Base.metadata。

   干啥用：Alembic 建迁移、create_all 建表，读的都是 Base.metadata
          所以每个模型文件必须 import 本文件，否则那张表就是"黑户"，建表时被漏掉。

   补充：Alembic = 表结构的 git，给每一版表结构生成一个 "版本快照";
        要执行 `uv run Alembic revision --autogenerate -m "描述" ` -> 生成迁移脚本，“把库往模型的样子搬”
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全项目唯一声明基类。"""
    pass
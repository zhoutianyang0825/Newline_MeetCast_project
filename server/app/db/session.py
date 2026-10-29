"""数据库会话层：engine 惰性单例，import 零副作用（PrismEdu D9 同款）。

 得到的数据：get_engine / get_session_factory / get_session 三个入口
 
 关键设计：惰性创建——import 本模块不连库，连不上只在真正用库那一刻报错

DATABASE_URL 配置（settings.py 读入）：
    生产     postgresql+psycopg://user:pass@host:5432/meetcast
    开发默认 sqlite:///data/meetcast.db（零依赖即开即用，跨库模型已兼容）
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import DATABASE_URL


# PrismEdu session.py 同款：@lru_cache 实现单例——第一次调用真执行函数体，
# 之后所有调用直接返回上次结果，全进程只建一个 engine，不反复 new 连接池。
@lru_cache
def get_engine() -> Engine:
    """创建（进程内单例）SQLAlchemy engine。

    得到的数据：
        无（URL 来自 settings.DATABASE_URL）。

    要做的操作：
        @lru_cache 保证只建一次；SQLite 追加 check_same_thread=False
        （uvicorn 线程池 + APScheduler 并发访问）；PG 加 pool_pre_ping 防断连。

    返回：
        Engine 实例。

    为什么：import 即连库会让"跑个单测也要装驱动、连不上就崩"，惰性化后才安全。
    """
    if DATABASE_URL.startswith("sqlite"):
        return create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    # PrismEdu session.py 同款：pool_pre_ping 每次借连接前先探活，
    # 防止容器闲置后连接被掐、下一个请求拿到死连接报"隔夜第一请求错"。
    return create_engine(DATABASE_URL, pool_pre_ping=True)


# PrismEdu session.py 同款：工厂也单例——工厂全局一个（柜台共享），
# session 每请求一个（话机独占），两级调用缺一不可。
@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """创建（进程内单例）会话工厂。

    得到的数据：
        无。

    要做的操作：
        @lru_cache 保证只建一次；expire_on_commit=False——commit 后
        属性仍可读，不用二次查询。

    返回：
        sessionmaker 实例，调用它产生单个 Session。

    为什么：store 层每个方法是独立短会话，统一从一个工厂取，参数不漂移。
    """
    # PrismEdu session.py 同款：expire_on_commit=False，commit 后不再偷偷回库重查，
    # 避免 session 已关时报 DetachedInstanceError。
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """请求级会话（FastAPI 依赖注入用）。

    得到的数据：
        无。

    要做的操作：
        产出一个 Session，请求结束（含异常）自动 close。

    返回：
        Iterator[Session]，供 Depends(get_session) 消费。

    为什么：路由层未来直接注入会话时用；当前 store 层走短会话自管。
    """
    # PrismEdu get_db 同款：sessionmaker()() 两级调用才产出 session；
    # yield 前准备、yield 后善后，finally 保证异常也关连接不泄漏。
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

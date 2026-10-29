"""Newline MeetCast 服务端入口（16 个接口：设备端 3 + 管理端 11 + 免登录 2）

启动：cd server && uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app.db.session import get_engine
from app.files import UPLOAD_DIR, ensure_seed_material_file
from app.models import Base
from app.response import err_json
from app.settings import OFFLINE_SWEEP_INTERVAL_SEC, OFFLINE_TIMEOUT_SEC

from app.errors import (
    ApiError,
    CODE_INTERNAL,
    CODE_PARAM_INVALID,
    MESSAGES,
)
from app.routers import (
    auth,
    admin_calendar,
    admin_commands,
    admin_devices,
    admin_materials,
    admin_rooms,
    device,
    upload,
)
from app.store import seed, store

# 离线判定阈值与扫描间隔统一在 settings（90s ≈ 3 次×30s 心跳）
app = FastAPI(
    title="Newline MeetCast Server",
    version="0.1.0",
    description="16 接口：设备端 3（poll/ack/heartbeat）+ 管理端 11（设备/素材/日历/运维）+ 免登录 2（上传）· 对齐 Newline_MeetCast_API_Spec.md v0.2",
)


# ---- 生命周期：启动时灌种子数据 + 起离线扫描后台任务 ----

async def _offline_sweeper() -> None:
    """后台任务：周期扫描离线设备。

    得到的数据：
        无入参（阈值取 OFFLINE_TIMEOUT_SEC=90，间隔取 OFFLINE_SWEEP_INTERVAL_SEC=15）。

    要做的操作：
        每 15s 调 store.sweep_offline()；
        被标记 offline 的设备逐台打一行日志。

    返回：
        无（常驻协程，lifespan 关停时 cancel）。

    为什么：F1.2 验收口径——连续 3 次心跳缺失（90 秒）内要反映到后台。
    """
    while True:
        await asyncio.sleep(OFFLINE_SWEEP_INTERVAL_SEC)
        for device_id in store.sweep_offline(timeout_sec=OFFLINE_TIMEOUT_SEC):
            print(f"[offline] {device_id} 连续 90s 无心跳，已标记 offline")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动灌种子数据 + 起离线扫描，关停时收尾。

    得到的数据：
        _app（FastAPI 实例，协议占位参数，未用）。

    要做的操作：
        启动段：建表（幂等 create_all，正式口径走 Alembic 0001）→ seed(store) 灌演示数据；
        起离线扫描与调度器（日历→指令）；
        yield 挂起，让出服务运行期；
        关停段：停调度器、cancel 离线扫描任务。

    返回：
        无（async 上下文管理器，FastAPI lifespan 协议）。

    为什么：种子数据让服务一启动就能联调；调度器一起，日历驱动的切屏就不再需要手工造指令。
    """
    Base.metadata.create_all(bind=get_engine())   # 幂等建表（表结构演进走 alembic 0002+）
    seed(store)                       # 演示设备 / 会议 / 素材 / 上传 token（幂等，已灌过即跳过）
    ensure_seed_material_file()       # 种子素材补一份实体文件，设备预拉取才不会 404
    scheduler.start()                 # D2：日历 → 状态机 → 指令队列（启动即跑一次）
    task = asyncio.create_task(_offline_sweeper())
    yield
    scheduler.shutdown()
    task.cancel()                     # 优雅关停后台任务


app.router.lifespan_context = lifespan


# ---- 统一异常处理：任何错误都走 { code, message, data: null } 壳（壳出口在 app/response.py） ----

@app.exception_handler(ApiError)
async def api_error_handler(_req: Request, exc: ApiError) -> JSONResponse:
    """业务异常（raise ApiError(...)）→ 统一错误壳"""
    return err_json(exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_req: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 入参校验失败 → 1001（缺字段/类型错/枚举值非法）"""
    first = exc.errors()[0] if exc.errors() else {}
    detail = f"{first.get('loc', '')}: {first.get('msg', '')}"
    return err_json(CODE_PARAM_INVALID, f"{MESSAGES[CODE_PARAM_INVALID]}（{detail}）")


@app.exception_handler(Exception)
async def unexpected_error_handler(_req: Request, exc: Exception) -> JSONResponse:
    """兜底：未预期异常 → 5000（不把堆栈泄给设备端）"""
    print(f"[5000] unexpected error: {exc!r}")
    return err_json(CODE_INTERNAL, MESSAGES[CODE_INTERNAL])


# ---- 路由注册（16 个接口：设备端 3 + 管理端 11 + 免登录 2） ----

app.include_router(auth.router)
app.include_router(device.router)
app.include_router(admin_devices.router)
app.include_router(admin_rooms.router)
app.include_router(admin_materials.router)
app.include_router(upload.router)
app.include_router(admin_calendar.router)
app.include_router(admin_commands.router)


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    """健康检查（部署探活用，不走设备认证）"""
    return {"code": 0, "message": "ok", "data": {"service": "meetcast-server", "version": "0.1.0"}}


# 素材静态访问：/media/<file> 直接下载落盘文件，url 字段据此拼（换 OSS 只改域名）
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=UPLOAD_DIR), name="media")

# 前端页面（大屏 meeting/signage/boot、上传页、后台、设备模拟屏）：/ui/xxx.html
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")

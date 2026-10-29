"""统一响应壳出口：成功壳 ok()，错误壳在 main.py 异常 handler 里。"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.errors import MESSAGES, CODE_OK


def ok(data: Any) -> dict:
    """包成功响应壳。

    得到的数据：
        data（业务数据，可为 None）。

    要做的操作：
        拼成统一外壳 {code:0, message:"ok", data}。

    返回：
        {"code": 0, "message": "ok", "data": {"items": [...], "total": 12}}

    为什么：成功壳全项目只有这一个出口，设备端/管理端共用；错误壳由异常 handler 负责。
    """
    return {"code": CODE_OK, "message": MESSAGES[CODE_OK], "data": data}


def err_json(code: int, message: str) -> JSONResponse:
    """包统一错误壳（仅 main.py 异常 handler 用）。

    得到的数据：
        code（错误码，如 2001）；message（人看的提示语，如 "设备不存在"）。

    要做的操作：
        拼成 {"code": ..., "message": ..., "data": None}，HTTP 状态固定 200。

    返回：
        JSONResponse，如 {"code": 2001, "message": "设备不存在", "data": null}

    为什么：客户端只认业务码不解析 HTTP 状态，全部 200 省掉客户端的状态码分支。
    """
    return JSONResponse(status_code=200, content={"code": code, "message": message, "data": None})

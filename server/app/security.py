"""认证依赖：设备端 X-Device-Key（规范 §一）+ 管理端 JWT Bearer（规范 §三）"""

from __future__ import annotations

from fastapi import Header

from app.errors import ApiError, CODE_DEVICE_NOT_FOUND, CODE_NO_PERMISSION, CODE_UNAUTHORIZED
from app.jwtauth import decode_token
from app.store import Device, store


def auth_device(x_device_key: str = Header(..., alias="X-Device-Key")) -> Device:
    """X-Device-Key 请求头 → 设备行（3 个设备接口共用的认证依赖）。

    得到的数据：
        x_device_key（FastAPI 从请求头 X-Device-Key 注入，如 "dev-key-sh-a3-01-01"）。

    要做的操作：
        按密钥反查设备，查不到 → 1002（未认证）；
        密钥对但设备被删 → 2001（设备不存在）。

    返回：
        Device 行（路由参数接住，路由里直接用 device.xxx）。

    为什么：3 个接口共用同一套认证，收口成一个依赖，路由里零重复。
    """
    device = store.get_device_by_key(x_device_key)
    if device is None:
        raise ApiError(CODE_UNAUTHORIZED)
    if not store.device_exists(device.device_id):
        raise ApiError(CODE_DEVICE_NOT_FOUND)
    return device


def auth_admin(authorization: str | None = Header(None)) -> str:
    """JWT Bearer → 管理员 user_id（管理端接口共用的认证依赖）。

    得到的数据：
        authorization（"Authorization: Bearer eyJ..." 整串，FastAPI 自动注入，可缺省）。

    要做的操作：
        头缺失 / 无 "Bearer " 前缀 / 签名或过期校验失败 → 1002；
        payload.role 不是 admin → 1003（无权限）。

    返回：
        user_id 字符串，如 "admin_001"（路由里拼 initiated_by=admin:<user_id>，F8.3）。

    为什么：所有管理端接口共用，且 user_id 必须逐请求带出来做审计；
            头声明为可选，缺头走业务码 1002 而不是被入参校验拦成 1001。
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApiError(CODE_UNAUTHORIZED)
    payload = decode_token(authorization[len("Bearer "):])
    if payload is None:
        raise ApiError(CODE_UNAUTHORIZED)
    if payload.get("role") != "admin":
        raise ApiError(CODE_NO_PERMISSION)
    return payload["sub"]


def auth_user(authorization: str | None = Header(None)) -> str:
    """JWT Bearer → 已登录 user_id（普通用户与管理员都放行，F8.1）。

    得到的数据：
        authorization（Authorization 头，可缺省）。

    要做的操作：
        与 auth_admin 同样的签名/过期校验，但**不校验角色**。

    返回：
        user_id 字符串，如 "user_001"。

    为什么：PRD F8.1 规定普通用户可"上传素材、查看会议室与设备"，
            这几个读/上传接口不能要求 admin，否则普通用户寸步难行。
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApiError(CODE_UNAUTHORIZED)
    payload = decode_token(authorization[len("Bearer "):])
    if payload is None:
        raise ApiError(CODE_UNAUTHORIZED)
    return payload["sub"]

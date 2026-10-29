"""登录接口（F8.1 / F8.2 账号体系的最小可用版）

POST /api/auth/login  email + password → JWT
GET  /api/auth/me     回显当前身份（前端刷新页面时用）

规范 §一原本只有"管理端 Bearer <JWT>"，没有签发入口；本接口是补充的第 17 个接口，
已同步写进 docs/Newline_MeetCast_API_Spec.md §十。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.errors import ApiError, CODE_PARAM_INVALID, CODE_UNAUTHORIZED
from app.jwtauth import create_token
from app.response import ok
from app.schemas import LoginOut, LoginRequest
from app.security import auth_user
from app.store import store
from app.users import verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(req: LoginRequest) -> dict:
    """邮箱 + 口令登录，签发 JWT。

    得到的数据：
        req（email 如 "admin@honghe.com"；password 如 "admin123"）。

    要做的操作：
        邮箱不存在 / 口令不对 → 统一 1002（不区分，防账号枚举）；
        通过 → 按用户角色签发 8 小时 JWT。

    返回：
        {"token": "eyJ...", "user_id": "admin_001", "name": "管理员",
         "role": "admin", "expires_in": 28800}

    为什么：管理端 11 个接口都要 JWT，没有签发入口就只能手写脚本造 token（联调很难受）。
    """
    email = req.email.strip().lower()
    if not email or not req.password:
        raise ApiError(CODE_PARAM_INVALID, "email 与 password 必填")
    user = store.get_user_by_email(email)
    if user is None or not verify_password(req.password, user):
        raise ApiError(CODE_UNAUTHORIZED, "邮箱或密码错误")
    expires_sec = 8 * 3600
    token = create_token(user.user_id, role=user.role, expires_sec=expires_sec)
    return ok(LoginOut(
        token=token,
        user_id=user.user_id,
        name=user.name,
        role=user.role,
        expires_in=expires_sec,
    ).model_dump())


@router.get("/me")
def me(user_id: str = Depends(auth_user)) -> dict:
    """回显当前登录身份。

    得到的数据：
        user_id（认证依赖从 JWT 解出）。

    要做的操作：
        按 user_id 在用户表里找这个人。

    返回：
        {"user_id": "admin_001", "name": "管理员", "role": "admin"}

    为什么：前端刷新页面时要知道"我还登录着吗、我是什么角色"，避免每次靠试接口判断。
    """
    user = store.get_user_by_id(user_id)
    if user is None:
        raise ApiError(CODE_UNAUTHORIZED)
    return ok({"user_id": user.user_id, "name": user.name, "role": user.role})

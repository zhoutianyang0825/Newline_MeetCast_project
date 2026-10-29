"""E 组冒烟：账号与角色（F8.1 / F8.2）

用法：cd server && uv run python scripts/mock_auth.py
不依赖 HTTP（登录接口另有 HTTP 验证），这里直接测口令与角色判定。

冒烟序列：
  ① 口令 hash 校验：对的能过、错的不过
  ② 管理员 token 能过 auth_admin
  ③ 普通用户 token 过不了 auth_admin（1003）
  ④ 普通用户 token 能过 auth_user（F8.1 允许看设备/传素材）
  ⑤ 伪造 token 过不了任何依赖（1002）
  ⑥ 登录签发 8 小时有效期
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

from app.errors import ApiError  # noqa: E402
from app.jwtauth import create_token, decode_token  # noqa: E402
from app.security import auth_admin, auth_user  # noqa: E402
from app.store import seed, store  # noqa: E402
from app.users import hash_password, verify_password  # noqa: E402


def check(step: str, cond: bool, extra: str = "") -> None:
    """断言并打印，失败即退出"""
    mark = "PASS" if cond else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not cond:
        sys.exit(1)


def expect_code(fn, code: int) -> tuple[bool, str]:
    """调用应抛 ApiError 的依赖，返回 (是否符合预期错误码, 实际消息)"""
    try:
        fn()
        return False, "未抛异常"
    except ApiError as exc:
        return exc.code == code, f"code={exc.code}"


def main() -> None:
    seed(store)
    admin = store.get_user_by_email("admin@honghe.com")
    ops = store.get_user_by_email("ops@honghe.com")

    # ① 口令
    check("① 管理员口令正确", verify_password("admin123", admin))
    check("① 错误口令被拒", not verify_password("admin124", admin))
    digest, salt = hash_password("x")
    check("① 加盐 hash 长度 64", len(digest) == 64 and len(salt) == 32)

    # ② 管理员 token 过 auth_admin
    admin_token = create_token(admin.user_id, role="admin")
    check("② 管理员可通过 auth_admin", auth_admin(f"Bearer {admin_token}") == "admin_001")

    # ③ 普通用户 token 过不了 auth_admin
    user_token = create_token(ops.user_id, role="user")
    ok_flag, msg = expect_code(lambda: auth_admin(f"Bearer {user_token}"), 1003)
    check("③ 普通用户被 auth_admin 拒（1003）", ok_flag, msg)

    # ④ 普通用户过 auth_user
    check("④ 普通用户可通过 auth_user", auth_user(f"Bearer {user_token}") == "user_001")

    # ⑤ 伪造 token
    ok_flag, msg = expect_code(lambda: auth_user("Bearer fake.token.here"), 1002)
    check("⑤ 伪造 token 被拒（1002）", ok_flag, msg)

    # ⑥ 有效期
    payload = decode_token(admin_token)
    left = payload["exp"] - int(time.time())
    check("⑥ 有效期为 8 小时", 8 * 3600 - 60 <= left <= 8 * 3600, f"{left}s")

    print("\n=== E 组冒烟 8 项全过：口令校验 + 管理员/普通用户角色 + token 有效期 OK ===")


if __name__ == "__main__":
    main()

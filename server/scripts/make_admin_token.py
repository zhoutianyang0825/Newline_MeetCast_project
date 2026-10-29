"""离线签发管理端 dev JWT（开发期无登录接口，规范 §三 的 token 从这来）

用法：cd server && uv run python scripts/make_admin_token.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ 不在包路径里，手动把 server 根目录塞进 sys.path，才能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.jwtauth import create_token  # noqa: E402


def main() -> None:
    """打印一枚 dev 管理员 token + 用法示例。

    要做的操作：
        create_token("admin_001") 签发 8 小时有效的 admin token；
        打印 token 和 curl 示例，复制即用。

    为什么：16 个接口里 11 个管理端接口都要 JWT，联调前先用它造一枚。
    """
    token = create_token(user_id="admin_001")
    print(f"ADMIN_TOKEN={token}\n")
    print("curl 示例：")
    print(f'  curl -H "Authorization: Bearer {token}" http://localhost:8000/api/admin/devices')


if __name__ == "__main__":
    main()

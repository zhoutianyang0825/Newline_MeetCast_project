"""账号与口令（F8.1 / F8.2 简化版：只保留 普通用户 + 管理员）

口令不存明文：PBKDF2-HMAC-SHA256 + 每用户随机盐，校验用 compare_digest（常数时间）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

# 迭代次数：本机 demo 取 12 万，生产可上调（越大越慢越安全）
PBKDF2_ITERATIONS = 120_000


@dataclass
class User:
    """用户行。

    字段：user_id（如 "admin_001"）；email（登录名）；name（展示名）；role（admin / user）；password_hash（PBKDF2 派生值）；salt（随机盐）。
    """

    user_id: str
    email: str
    name: str
    role: str
    password_hash: str = ""
    salt: str = ""


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """口令 → (hash, salt)。

    得到的数据：
        password（明文，如 "admin123"）；salt（可选，不传则随机生成）。

    要做的操作：
        PBKDF2-HMAC-SHA256 迭代 12 万次，输出十六进制。

    返回：
        ("9f2c...", "3a1b...")（hash, salt）

    为什么：库里绝不落明文；加盐让彩虹表失效，compare_digest 防时序攻击。
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, user: User) -> bool:
    """校验口令。

    得到的数据：
        password（用户输入）；user（库里的用户行，含 salt 与 password_hash）。

    要做的操作：
        用同一盐重算，与库里 hash 做常数时间比较。

    返回：
        True / False

    为什么：登录是唯一入口，比较必须防时序侧信道，也不能因为字段缺失就抛异常。
    """
    if not user.password_hash or not user.salt:
        return False
    digest, _ = hash_password(password, user.salt)
    return hmac.compare_digest(digest, user.password_hash)


def make_user(user_id: str, email: str, name: str, role: str, password: str) -> User:
    """造一个用户行（种子数据/新增用户用）。

    得到的数据：
        user_id / email / name / role / password（明文，仅此处用于派生）。

    要做的操作：
        派生 hash+salt 后组 User。

    返回：
        User(user_id="admin_001", email="admin@honghe.com", role="admin", ...)

    为什么：种子与后续"新增用户"共用同一个构造逻辑，避免两处派生方式不一致。
    """
    digest, salt = hash_password(password)
    return User(user_id=user_id, email=email, name=name, role=role, password_hash=digest, salt=salt)

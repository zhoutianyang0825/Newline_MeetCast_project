"""JWT 签发与校验（管理端认证用，HS256，纯标准库实现）

规范 §一：管理端 Authorization: Bearer <JWT>。开发期无登录接口，
用 scripts/make_admin_token.py 离线签发 dev token。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.settings import JWT_SECRET

# 签名密钥：统一从 settings 取（生产用环境变量 MEETCAST_JWT_SECRET 注入）
SECRET = JWT_SECRET


def _b64url_encode(raw: bytes) -> str:
    # 陌生点 base64.urlsafe_b64encode：JWT 规定用 URL 安全 base64（- _ 替换 + /）。
    #   是什么：二进制 → 文本的无损编码，去掉了尾部的 = 填充；
    #   起什么作用：header/payload/signature 三段都编码成它能直接拼进 URL/请求头；
    #   为什么用：JWT 标准要求，不用它解码端对不上。
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    # 补回被去掉的 = 填充再解码；解码失败由调用方兜住
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_token(user_id: str, role: str = "admin", expires_sec: int = 8 * 3600) -> str:
    """签发 JWT。

    得到的数据：
        user_id（管理员标识，如 "admin_001"，审计 initiated_by 用）；
        role（角色，固定 "admin"）；expires_sec（有效期秒数，默认 8 小时）。

    要做的操作：
        拼 header/payload 两段 JSON → base64url；
        用 HMAC-SHA256 对前两段签名，拼成三段式 token。

    返回：
        "eyJhbGciOi.eyJzdWIiOi....KmRfPz..."（三段点分字符串）

    为什么：管理端接口都要"谁在操作"（initiated_by=admin:<user_id>，F8.3），
            JWT 的 payload 天然携带 user_id 和 role。
    """
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "role": role,
        "exp": int(time.time()) + expires_sec,
    }
    # 两段各自 base64url 后用 . 连，作为待签名原文
    signing_input = _b64url_encode(json.dumps(header).encode()) + "." + _b64url_encode(json.dumps(payload).encode())
    # 陌生点 hmac.new：带密钥的哈希。
    #   是什么：HMAC-SHA256 = 密钥参与运算的 SHA256；
    #   起什么作用：只有持 SECRET 的人能算出/验证签名，改一个字节签名就对不上；
    #   为什么用：防 token 被伪造（改 role=user 也过不了校验）。
    signature = hmac.new(SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url_encode(signature)


def decode_token(token: str) -> dict | None:
    """校验并解出 JWT payload。

    得到的数据：
        token（请求头 Bearer 后面的那串）。

    要做的操作：
        按点拆三段，重算签名比对（防篡改）；
        签名对 → 解 payload，exp 过期也算无效。

    返回：
        {"sub": "admin_001", "role": "admin", "exp": 1760000000}；
        格式错/签名不对/过期 → None（调用方转 1002）。

    为什么：认证失败必须统一收敛成 None，让路由层只关心业务分支。
    """
    try:
        signing_input, _, signature_b64 = token.rpartition(".")
        expected = hmac.new(SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        # 比对签名：hmac.compare_digest 是常数时间比较，防时序攻击
        if not hmac.compare_digest(_b64url_decode(signature_b64), expected):
            return None
        payload_b64 = signing_input.split(".")[1]
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

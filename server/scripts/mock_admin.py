"""管理端模拟器：冒烟验证设备管理 3 接口（规范 §三）

用法：cd server && uv run python scripts/mock_admin.py
前置：先跑 uv run python scripts/make_admin_token.py？不用——本脚本自己签 token。

冒烟序列（认证 → 列表 → 绑定 → 解绑，错误码全覆盖）：
  ① 无 token / 假 token          → 1002
  ② 非管理员 token               → 1003
  ③ 设备列表                     → code=0，total≥2
  ④ 列表 status 非法             → 1001
  ⑤ bind 设备不存在              → 2001
  ⑥ bind 会议室不存在            → 2003
  ⑦ bind 已绑设备未 force        → 2002
  ⑧ bind 被占会议室未 force      → 2008
  ⑨ bind force 换绑              → code=0，effective_in_sec=300
  ⑩ unbind                       → code=0，再查列表 room_id 为 null
  ⑪ unbind 设备不存在            → 2001
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.jwtauth import create_token  # noqa: E402

BASE_URL = "http://localhost:8000"


def admin_headers(token: str) -> dict:
    """拼 Bearer 头"""
    return {"Authorization": f"Bearer {token}"}


def check(step: str, got: int, want: int, extra: str = "") -> None:
    """断言业务码并打印结果，失败即退出"""
    mark = "PASS" if got == want else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}  → code={got}（期望 {want}）{suffix}")
    if got != want:
        sys.exit(1)


def main() -> None:
    good_token = create_token("admin_001")       # 正确管理员 token
    evil_token = create_token("intern_001", role="user")  # 非管理员 token

    with httpx.Client(timeout=10) as client:
        # ① 认证失败 → 1002
        r = client.get(f"{BASE_URL}/api/admin/devices").json()
        check("① 无 token", r["code"], 1002)
        r = client.get(f"{BASE_URL}/api/admin/devices", headers=admin_headers("fake.token.x")).json()
        check("① 假 token", r["code"], 1002)

        # ② 普通用户：能看设备列表（F8.1），但不能绑定（1003）
        r = client.get(f"{BASE_URL}/api/admin/devices", headers=admin_headers(evil_token)).json()
        check("② 普通用户可查看设备列表", r["code"], 0, f"total={r['data']['total']}")
        r = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=admin_headers(evil_token),
                        json={"device_id": "SH-A3-01-02", "room_id": "room-b2-05"}).json()
        check("② 普通用户不能绑定（1003）", r["code"], 1003)

        # ③ 设备列表：种子里 2 台
        r = client.get(f"{BASE_URL}/api/admin/devices", headers=admin_headers(good_token)).json()
        check("③ 设备列表", r["code"], 0, f"total={r['data']['total']}")
        assert r["data"]["total"] >= 2
        first = r["data"]["items"][0]
        assert "room_name" in first and "device_state" in first

        # ④ status 过滤值非法 → 1001
        r = client.get(f"{BASE_URL}/api/admin/devices?status=bogus", headers=admin_headers(good_token)).json()
        check("④ 列表 status 非法", r["code"], 1001)

        # ⑤ bind 设备不存在 → 2001
        r = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=admin_headers(good_token),
                        json={"device_id": "NO-DEV", "room_id": "room-b2-05"}).json()
        check("⑤ bind 设备不存在", r["code"], 2001)

        # ⑥ bind 会议室不存在 → 2003
        r = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=admin_headers(good_token),
                        json={"device_id": "SH-A3-01-02", "room_id": "NO-ROOM"}).json()
        check("⑥ bind 会议室不存在", r["code"], 2003)

        # ⑦ SH-A3-01-01 种子已绑 room-a3-01，未 force 再绑 → 2002
        r = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=admin_headers(good_token),
                        json={"device_id": "SH-A3-01-01", "room_id": "room-b2-05"}).json()
        check("⑦ bind 已绑设备未 force", r["code"], 2002)

        # ⑧ room-a3-01 已被 SH-A3-01-01 占用，另一台未 force 抢占 → 2008
        r = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=admin_headers(good_token),
                        json={"device_id": "SH-A3-01-02", "room_id": "room-a3-01"}).json()
        check("⑧ bind 被占会议室未 force", r["code"], 2008)

        # ⑨ force 换绑 SH-A3-01-01 → room-bcn-01 → code=0
        r = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=admin_headers(good_token),
                        json={"device_id": "SH-A3-01-01", "room_id": "room-bcn-01", "force": True}).json()
        check("⑨ bind force 换绑", r["code"], 0,
              f"effective_in_sec={r['data']['effective_in_sec']}")

        # ⑩ unbind → room_id 清空
        r = client.post(f"{BASE_URL}/api/admin/devices/unbind", headers=admin_headers(good_token),
                        json={"device_id": "SH-A3-01-01"}).json()
        check("⑩ unbind", r["code"], 0)
        r = client.get(f"{BASE_URL}/api/admin/devices?device_id=SH-A3-01-01", headers=admin_headers(good_token)).json()
        target = next(d for d in r["data"]["items"] if d["device_id"] == "SH-A3-01-01")
        assert target["room_id"] is None and target["room_name"] is None

        # ⑪ unbind 设备不存在 → 2001
        r = client.post(f"{BASE_URL}/api/admin/devices/unbind", headers=admin_headers(good_token),
                        json={"device_id": "NO-DEV"}).json()
        check("⑪ unbind 设备不存在", r["code"], 2001)

    print("\n=== 冒烟 11 项全过：管理端设备 3 接口（list / bind / unbind）闭环 OK ===")


if __name__ == "__main__":
    main()

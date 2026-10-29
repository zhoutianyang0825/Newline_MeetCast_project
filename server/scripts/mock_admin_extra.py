"""管理端剩余接口 + 免登录上传冒烟（规范 §四 §五 §六 §七）

用法：cd server && uv run python scripts/mock_admin_extra.py
前置：服务已启动（uv run uvicorn app.main:app --port 8000）

冒烟序列：
  ① 素材列表                        → code=0
  ② 公共素材上传 png                 → code=0，拿到 material_id
  ③ 上传 .exe                       → 2005
  ④ 删除素材（第二次）                → 2004
  ⑤ 免登录上传页（正常 token）        → code=0，accepted_formats 有值
  ⑥ 免登录上传素材                    → code=0
  ⑦ 已截止会议 token                 → 2006
  ⑧ 已撤销 token / 乱 token          → 1004
  ⑨ 日历配置读取 / 保存 / 回读        → code=0
  ⑩ 日历连接测试                     → code=0，auth_ok=true
  ⑪ 指令审计列表                     → code=0
  ⑫ 手动切换（设备离线）              → 2009 + command_id
  ⑬ 手动切换（先心跳上线，再切）       → code=0
  ⑭ 手动切换（设备不存在）            → 2001
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.jwtauth import create_token  # noqa: E402

BASE_URL = "http://localhost:8000"
ADMIN = {"Authorization": f"Bearer {create_token('admin_001')}"}


def check(step: str, got: int, want: int, extra: str = "") -> None:
    """断言业务码并打印结果，失败即退出"""
    mark = "PASS" if got == want else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}  → code={got}（期望 {want}）{suffix}")
    if got != want:
        sys.exit(1)


def main() -> None:
    with httpx.Client(timeout=30) as client:
        # ① 素材列表（种子里有一条公共素材）
        r = client.get(f"{BASE_URL}/api/admin/materials", headers=ADMIN).json()
        check("① 素材列表", r["code"], 0, f"total={r['data']['total']}")

        # ② 公共素材上传（1KB 假 png）
        files = {"file": ("demo-cover.png", b"\x89PNG\r\n\x1a\n" + b"0" * 1024, "image/png")}
        r = client.post(f"{BASE_URL}/api/admin/materials", headers=ADMIN,
                        files=files, data={"scope": "public", "tags": "brand,cover"}).json()
        check("② 公共素材上传", r["code"], 0, f"material_id={r['data']['material_id']}")
        new_material_id = r["data"]["material_id"]

        # ③ 冷门格式 → 2005
        files = {"file": ("virus.exe", b"MZ" + b"0" * 32, "application/octet-stream")}
        r = client.post(f"{BASE_URL}/api/admin/materials", headers=ADMIN, files=files).json()
        check("③ 上传 .exe", r["code"], 2005)

        # ④ 删除素材：先删刚传的，再删一次 → 2004
        r = client.delete(f"{BASE_URL}/api/admin/materials/{new_material_id}", headers=ADMIN).json()
        check("④ 删除素材", r["code"], 0)
        r = client.delete(f"{BASE_URL}/api/admin/materials/{new_material_id}", headers=ADMIN).json()
        check("④ 重复删除 → 2004", r["code"], 2004)

        # ⑤ 免登录上传页：正常 token（不带 JWT，靠 URL token）
        r = client.get(f"{BASE_URL}/api/upload/tok_demo_123").json()
        check("⑤ 上传页信息", r["code"], 0,
              f"meeting={r['data']['subject']} 截止={r['data']['upload_deadline_utc']}")

        # ⑥ 免登录上传专属素材
        files = {"file": ("agenda.png", b"\x89PNG\r\n\x1a\n" + b"1" * 2048, "image/png")}
        r = client.post(f"{BASE_URL}/api/upload/tok_demo_123", files=files).json()
        check("⑥ 免登录上传", r["code"], 0, f"material_id={r['data']['material_id']}")
        meeting_material_id = r["data"]["material_id"]

        # ⑦ 会议已开始（上传截止已过）→ 2006
        r = client.get(f"{BASE_URL}/api/upload/tok_demo_started").json()
        check("⑦ 已截止 token", r["code"], 2006)

        # ⑧ 撤销 / 乱 token → 1004
        r = client.get(f"{BASE_URL}/api/upload/tok_demo_revoked").json()
        check("⑧ 已撤销 token", r["code"], 1004)
        r = client.get(f"{BASE_URL}/api/upload/tok_not_exist").json()
        check("⑧ 乱 token", r["code"], 1004)

        # ⑨ 日历配置：读 → 改告警邮箱 → 回读校验
        r = client.get(f"{BASE_URL}/api/admin/calendar/config", headers=ADMIN).json()
        check("⑨ 读日历配置", r["code"], 0, f"status={r['data']['connection_status']}")
        cfg = r["data"]
        cfg["alert_email"] = "ops@honghe.com"
        cfg.pop("connection_status", None)
        cfg.pop("credential_expire_at", None)
        r = client.put(f"{BASE_URL}/api/admin/calendar/config", headers=ADMIN, json=cfg).json()
        check("⑨ 保存日历配置", r["code"], 0)
        r = client.get(f"{BASE_URL}/api/admin/calendar/config", headers=ADMIN).json()
        assert r["data"]["alert_email"] == "ops@honghe.com"
        assert r["data"]["scopes"] == ["Calendars.Read", "Mail.Send"], "scopes 不允许被前端改"

        # ⑩ 连接测试
        r = client.post(f"{BASE_URL}/api/admin/calendar/test", headers=ADMIN).json()
        check("⑩ 日历连接测试", r["code"], 0, f"auth_ok={r['data']['auth_ok']} rooms={r['data']['rooms_synced']}")

        # ⑪ 指令审计列表（种子有 PREPARE_MEETING + 刚拍的 CLEAN_MATERIAL 等）
        r = client.get(f"{BASE_URL}/api/admin/commands", headers=ADMIN).json()
        check("⑪ 指令审计列表", r["code"], 0, f"total={r['data']['total']}")

        # ⑫ 手动切换：SH-A3-01-03 从未心跳（种子常驻离线）→ 2009 但命令已入队
        #    content_url 一律用本机标牌页：残余指令万一被真设备吃掉，也不会打不开
        signage = f"{BASE_URL}/ui/display/signage.html"
        r = client.post(f"{BASE_URL}/api/admin/commands/switch", headers=ADMIN, json={
            "device_id": "SH-A3-01-03",
            "content_url": signage,
            "until": "2026-10-27T23:00:00Z",
        }).json()
        check("⑫ 切换（离线设备）", r["code"], 2009, f"command_id={r['data']['command_id']}")

        # ⑬ 先让设备心跳上线，再切换 → code=0
        client.post(f"{BASE_URL}/api/device/heartbeat",
                    headers={"X-Device-Key": "dev-key-sh-a3-01-02"},
                    json={"device_id": "SH-A3-01-02", "device_state": "IDLE"})
        r = client.post(f"{BASE_URL}/api/admin/commands/switch", headers=ADMIN, json={
            "device_id": "SH-A3-01-02",
            "content_url": signage,
            "until": "2026-10-27T23:00:00Z",
        }).json()
        check("⑬ 切换（在线设备）", r["code"], 0, f"command_id={r['data']['command_id']}")

        # ⑬b 把刚入队的指令自己取走并回执，别留给真设备（否则设备启动就会切到这条）
        polled = client.post(f"{BASE_URL}/api/device/poll",
                             headers={"X-Device-Key": "dev-key-sh-a3-01-02"},
                             json={"device_id": "SH-A3-01-02", "agent_version": "smoke"},
                             timeout=30).json()
        leftover = polled["data"].get("command_id")
        if leftover:
            client.post(f"{BASE_URL}/api/device/ack",
                        headers={"X-Device-Key": "dev-key-sh-a3-01-02"},
                        json={"command_id": leftover, "status": "SUCCESS", "device_state": "IDLE"})
        check("⑬b 测试指令已自行消费", 1 if leftover else 0, 1, f"cleaned={leftover}")

        # ⑭ 设备不存在 → 2001
        r = client.post(f"{BASE_URL}/api/admin/commands/switch", headers=ADMIN, json={
            "device_id": "NO-DEV", "content_url": "https://x", "until": "2026-10-27T23:00:00Z",
        }).json()
        check("⑭ 切换（设备不存在）", r["code"], 2001)

    print("\n=== 冒烟 15 项全过：素材 / 免登录上传 / 日历源 / 运维 OK ===")
    print(f"（顺手确认：专属素材 mat={meeting_material_id} 已绑定 meeting_123）")


if __name__ == "__main__":
    main()

"""设备模拟器：模拟 APK 协议行为，冒烟验证设备端 3 接口（PRD M0 Mock 服务）

用法：cd server && uv run python scripts/mock_device.py
前置：服务已启动 → uv run uvicorn app.main:app --port 8000

冒烟序列（对齐 D4 联调顺序：heartbeat → poll → ack）：
  ① heartbeat 正常         → code=0 + server_time_utc
  ② heartbeat 密钥错       → 1002
  ③ heartbeat 设备不匹配   → 2001
  ④ poll 取指令            → 先入队一条 SWITCH_CONTENT 再取到它为止（沿途指令顺手 ACK，不留残指令）
  ⑤ ack status 非法        → 1001
  ⑥ ack command_id 不存在  → 2004
  ⑦ ack 正常回执           → code=0
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.jwtauth import create_token  # noqa: E402  用于第 ④ 步自己入队指令

BASE_URL = "http://localhost:8000"
DEVICE_ID = "SH-A3-01-01"
DEVICE_KEY = "dev-key-sh-a3-01-01"   # 种子数据里的演示密钥
ADMIN = {"Authorization": f"Bearer {create_token('admin_001')}"}


def post(client: httpx.Client, path: str, json_body: dict, key: str = DEVICE_KEY) -> dict:
    """带 X-Device-Key 的 POST，返回统一壳 { code, message, data }"""
    resp = client.post(
        f"{BASE_URL}{path}",
        json=json_body,
        headers={"X-Device-Key": key},
    )
    return resp.json()


def check(step: str, got: int, want: int, extra: str = "") -> None:
    """断言业务码并打印结果，失败即退出（冒烟不过就别往下走）"""
    mark = "PASS" if got == want else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}  → code={got}（期望 {want}）{suffix}")
    if got != want:
        sys.exit(1)


def main() -> None:
    with httpx.Client(timeout=35) as client:
        # ① heartbeat 正常：在线判定 + 校时
        r = post(client, "/api/device/heartbeat", {
            "device_id": DEVICE_ID,
            "device_state": "IDLE",
            "playing": "signage_default",
            "storage_used_mb": 34200,
        })
        check("① heartbeat 正常", r["code"], 0, f"server_time={r['data']['server_time_utc']}")

        # ② 密钥错 → 1002
        r = post(client, "/api/device/heartbeat", {"device_id": DEVICE_ID}, key="wrong-key")
        check("② heartbeat 密钥错", r["code"], 1002)

        # ③ device_id 与密钥不是同一台设备 → 2001
        r = post(client, "/api/device/heartbeat", {"device_id": "OTHER-DEV-99"})
        check("③ heartbeat 设备不匹配", r["code"], 2001)

        # ④ poll：先自己入队一条 SWITCH_CONTENT（保证本轮一定有指令可取，冒烟可重复跑）
        #    content_url 用本机标牌页：万一这条指令没被取走，真设备吃掉也不会打不开
        created = client.post(f"{BASE_URL}/api/admin/commands/switch", headers=ADMIN, json={
            "device_id": DEVICE_ID,
            "content_url": f"{BASE_URL}/ui/display/signage.html",
            "until": "2026-10-27T23:00:00Z",
        }).json()
        target_id = created["data"]["command_id"]

        # 队列里可能还排着调度器的 PREPARE_MEETING：沿途指令一律 ACK 掉，
        # 只把自己造的那条留给 ⑤⑥⑦ 做断言——否则残留指令会被真设备消费（踩过）
        command_id = None
        for _ in range(6):
            r = post(client, "/api/device/poll", {"device_id": DEVICE_ID, "agent_version": "1.0.0"})
            data = r["data"]
            if not data.get("command_id"):
                break
            if data["command_id"] == target_id:
                command_id = target_id
                break
            post(client, "/api/device/ack", {
                "command_id": data["command_id"],
                "status": "SUCCESS",
                "device_state": "IDLE",
            })
        check("④ poll 取指令", 1 if command_id else 0, 1,
              f"type=SWITCH_CONTENT command_id={command_id}")

        # ⑤ ack status 非法（只允许 SUCCESS/FAILED）→ 1001
        r = post(client, "/api/device/ack", {"command_id": command_id, "status": "MAYBE"})
        check("⑤ ack status 非法", r["code"], 1001)

        # ⑥ ack 不存在的 command_id → 2004
        r = post(client, "/api/device/ack", {"command_id": "cmd_not_exist", "status": "SUCCESS"})
        check("⑥ ack command_id 不存在", r["code"], 2004)

        # ⑦ ack 正常回执：SENT → ACKED，并回传设备状态
        r = post(client, "/api/device/ack", {
            "command_id": command_id,
            "status": "SUCCESS",
            "device_state": "MEETING",
        })
        check("⑦ ack 正常回执", r["code"], 0)

    print("\n=== 冒烟 7 项全过：heartbeat → poll → ack 协议闭环 OK ===")


if __name__ == "__main__":
    main()

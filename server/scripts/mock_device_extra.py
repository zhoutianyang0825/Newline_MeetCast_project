"""设备端新增 3 接口冒烟（profile / schedule / materials，规范 §2.4~2.6）

用法：cd server && uv run python scripts/mock_device_extra.py
前置：服务已启动；设备端 3 接口冒烟（mock_device.py）已通过

冒烟序列：
  ① profile 已绑定设备           → bound=true + room_name + timezone
  ② profile 密钥错               → 1002
  ③ profile 未绑定设备           → bound=false，room 字段为 null
  ④ schedule 已绑定设备          → 有日程、is_next 恰好一条、time_label 形如 "10:08 – 11:08"
  ⑤ schedule 的 content_url      → 指向 meeting.html 且带 meeting_id
  ⑥ schedule hours 非法          → 1001
  ⑦ schedule 未绑定设备          → items 为空
  ⑧ materials 已绑定设备         → 至少含公共素材，reason=public
  ⑨ materials 未绑定设备         → 只剩公共素材（专属素材不下发）
  ⑩ 绑定后再解绑：profile 跟随翻转 → 绑定后 bound=true，解绑后 bound=false
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.jwtauth import create_token  # noqa: E402

BASE_URL = "http://localhost:8000"
BOUND_DEVICE = "SH-A3-01-01"
BOUND_KEY = "dev-key-sh-a3-01-01"
SPARE_DEVICE = "SH-A3-01-02"          # 未绑定，供 bind/unbind 演练
SPARE_KEY = "dev-key-sh-a3-01-02"
ADMIN = {"Authorization": f"Bearer {create_token('admin_001')}"}


def get(client: httpx.Client, path: str, key: str, params: dict | None = None) -> dict:
    """带 X-Device-Key 的 GET，返回统一壳 { code, message, data }。"""
    resp = client.get(f"{BASE_URL}{path}", headers={"X-Device-Key": key}, params=params)
    return resp.json()


def check(step: str, got: int, want: int, extra: str = "") -> None:
    """断言业务码并打印结果，失败即退出。"""
    mark = "PASS" if got == want else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}  → code={got}（期望 {want}）{suffix}")
    if got != want:
        sys.exit(1)


def expect(step: str, ok: bool, extra: str = "") -> None:
    """断言布尔条件（用于字段级检查）。"""
    mark = "PASS" if ok else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not ok:
        sys.exit(1)


def main() -> None:
    with httpx.Client(timeout=30) as client:
        # 前置：把 02 号设备复位成"未绑定"，保证脚本可重复跑
        # （上一轮 ⑩ 或人工演示可能把它绑到某个会议室，不清就会让 ③⑦⑨ 失败）
        client.post(f"{BASE_URL}/api/admin/devices/unbind", headers=ADMIN,
                    json={"device_id": SPARE_DEVICE})

        # ① 已绑定设备：档案完整
        r = get(client, "/api/device/profile", BOUND_KEY)
        check("① profile 已绑定设备", r["code"], 0)
        d = r["data"]
        expect("① 档案字段", d["bound"] and d["room_id"] and d["room_name"] and d["timezone"],
               f"{d['device_id']} @ {d['room_name']} ({d['timezone']})")

        # ② 密钥错：1002
        r = get(client, "/api/device/profile", "wrong-key")
        check("② profile 密钥错", r["code"], 1002)

        # ③ 未绑定设备：bound=false
        r = get(client, "/api/device/profile", SPARE_KEY)
        check("③ profile 未绑定设备", r["code"], 0)
        d = r["data"]
        expect("③ 未绑定字段", (not d["bound"]) and d["room_id"] is None and d["room_name"] is None,
               f"room_id={d['room_id']}")

        # ④ 日程：有数据 + is_next 唯一 + 时间标签格式
        r = get(client, "/api/device/schedule", BOUND_KEY)
        check("④ schedule 已绑定设备", r["code"], 0)
        d = r["data"]
        expect("④ 日程非空", len(d["items"]) > 0, f"{len(d['items'])} 场，时区 {d['timezone']}")
        next_count = sum(1 for x in d["items"] if x["is_next"])
        expect("④ is_next 恰好一条", next_count <= 1, f"is_next={next_count}")
        label = d["items"][0]["time_label"]
        expect("④ time_label 格式", " – " in label, label)

        # ⑤ content_url 指向渲染页
        url = d["items"][0]["content_url"]
        expect("⑤ content_url 指向会议页", "/ui/display/meeting.html" in url and "meeting_id=" in url,
               url.split("?")[0])

        # ⑥ hours 越界：1001
        r = get(client, "/api/device/schedule", BOUND_KEY, params={"hours": 0})
        check("⑥ schedule hours=0", r["code"], 1001)

        # ⑦ 未绑定设备：日程为空
        r = get(client, "/api/device/schedule", SPARE_KEY)
        check("⑦ schedule 未绑定设备", r["code"], 0)
        expect("⑦ 未绑定无日程", len(r["data"]["items"]) == 0, f"items={len(r['data']['items'])}")

        # ⑧ 素材清单：含公共素材
        r = get(client, "/api/device/materials", BOUND_KEY)
        check("⑧ materials 已绑定设备", r["code"], 0)
        d = r["data"]
        publics = [x for x in d["items"] if x["reason"] == "public"]
        expect("⑧ 含公共素材", len(publics) >= 1, f"{d['count']} 条 / {d['total_mb']}MB")

        # ⑨ 未绑定设备：只剩公共素材（专属素材不下发）
        r = get(client, "/api/device/materials", SPARE_KEY)
        check("⑨ materials 未绑定设备", r["code"], 0)
        d2 = r["data"]
        expect("⑨ 未绑定只有公共素材",
               all(x["scope"] == "public" for x in d2["items"]),
               f"{d2['count']} 条，全 public")

        # ⑩ 绑定 → 解绑，profile 跟随翻转
        resp = client.post(f"{BASE_URL}/api/admin/devices/bind", headers=ADMIN,
                           json={"device_id": SPARE_DEVICE, "room_id": "room-b2-05", "force": True})
        check("⑩ 管理端绑定 02", resp.json()["code"], 0)
        r = get(client, "/api/device/profile", SPARE_KEY)
        expect("⑩ 绑定后 bound=true", r["data"]["bound"], f"room={r['data']['room_name']}")

        resp = client.post(f"{BASE_URL}/api/admin/devices/unbind", headers=ADMIN,
                           json={"device_id": SPARE_DEVICE})
        check("⑩ 管理端解绑 02", resp.json()["code"], 0)
        r = get(client, "/api/device/profile", SPARE_KEY)
        expect("⑩ 解绑后 bound=false", not r["data"]["bound"], "设备已回到未绑定态")

    print("\n设备端 profile/schedule/materials 三接口冒烟全过")


if __name__ == "__main__":
    main()

"""C/D 组冒烟：素材生命周期 + 编排策略（F4.8 / F4.2 / F3.4 / F3.5 / F4.3）

用法：cd server && uv run python scripts/mock_lifecycle.py
不依赖 HTTP，直接调 scheduler / layouts。

冒烟序列：
  ① 已到期的专属素材：记录被删 + 向房间设备下发 CLEAN_MATERIAL
  ② 重复清理不重复下发（幂等）
  ③ 未到期的专属素材不动
  ④ 标签过滤：按 tag 能筛出对应素材
  ⑤ 自动选版式：敏感→minimal（硬规则、不调模型）；
     配了 LLM → 选版结果须在白名单内且非敏感不降 minimal；没配 → 6 人 focus、2 人 standard
  ⑥ 时段标牌：按会议室本地小时落进早/中/晚三档
  ⑦ REPLAY 指令带时段标牌地址
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

from app import llm, scheduler  # noqa: E402
from app.layouts import LAYOUTS, pick_layout  # noqa: E402
from app.settings import SIGNAGE_SLOTS  # noqa: E402
from app.store import Material, Meeting, seed, shift_minutes, store, utc_now_iso  # noqa: E402
from app.tz import to_local  # noqa: E402


def check(step: str, cond: bool, extra: str = "") -> None:
    """断言并打印，失败即退出"""
    mark = "PASS" if cond else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not cond:
        sys.exit(1)


def main() -> None:
    seed(store)
    now = utc_now_iso()

    # 造一场会议 + 两条专属素材（一条已过期、一条未过期）
    store.upsert_meeting(Meeting(
        meeting_id="meeting_life",
        room_id="room-a3-01",
        subject="产品评审会",
        organizer_email="zhangsan@honghe.com",
        attendees=["张三", "李四"],
        start_time_utc=shift_minutes(now, -120),
        end_time_utc=shift_minutes(now, -60),
        timezone="Asia/Shanghai",
    ))
    store.add_material(Material(
        material_id="mat_expired", name="old.png", format="png", size_mb=1.0,
        url="/media/old.png", scope="meeting", meeting_id="meeting_life",
        expire_at=shift_minutes(now, -5), created_at=now,
    ))
    store.add_material(Material(
        material_id="mat_alive", name="new.png", format="png", size_mb=1.0,
        url="/media/new.png", scope="meeting", meeting_id="meeting_life",
        tags=["lifecycle-test"], expire_at=shift_minutes(now, 600), created_at=now,
    ))

    # ① 到期清理
    cleaned = scheduler.expire_materials()
    check("① 到期素材被清理", cleaned == 1 and store.get_material("mat_expired") is None, f"cleaned={cleaned}")
    clean_cmds = [c for c in store.all_commands()
                  if c.type == "CLEAN_MATERIAL" and c.payload.get("meeting_id") == "meeting_life"]
    check("① 下发 CLEAN_MATERIAL 到房间设备", len(clean_cmds) == 1,
          f"device={clean_cmds[0].device_id if clean_cmds else '无'}")

    # ② 幂等：再清一次不重复下发
    scheduler.expire_materials()
    again = [c for c in store.all_commands()
             if c.type == "CLEAN_MATERIAL" and c.payload.get("meeting_id") == "meeting_life"]
    check("② 重复清理不重复下发", len(again) == 1, f"{len(again)} 条")

    # ③ 未到期素材保留
    check("③ 未到期素材还在", store.get_material("mat_alive") is not None)

    # ④ 标签过滤
    rows, total = store.list_materials(scope=None, meeting_id=None, page=1, page_size=20, tag="lifecycle-test")
    check("④ 按 tag=lifecycle-test 筛出 1 条", total == 1 and rows[0].material_id == "mat_alive", f"total={total}")

    # ⑤ 自动选版式
    # 敏感 → minimal 是硬规则（任何配置下都成立，且不问模型）
    calls = {"n": 0}
    real_chat_json = llm.chat_json

    def counting_stub(*args, **kwargs):
        calls["n"] += 1
        return real_chat_json(*args, **kwargs)

    llm.chat_json = counting_stub
    try:
        sensitive_layout = pick_layout({"is_sensitive": True, "attendees": []})
    finally:
        llm.chat_json = real_chat_json
    check("⑤ 敏感 → minimal", sensitive_layout == "minimal", sensitive_layout)
    check("⑤ 敏感会议不调用模型", calls["n"] == 0, f"chat_json 调用 {calls['n']} 次")
    check("⑤ 三套版式都已定义", len(LAYOUTS) == 3, ",".join(LAYOUTS))

    if llm.available():
        # 配了模型：版式由模型决定，只校验"落在白名单内"且"非敏感会议不会被压成 minimal"
        for label, people in (("6 人", ["a"] * 6), ("2 人", ["a", "b"])):
            picked = pick_layout({"is_sensitive": False, "attendees": people,
                                  "subject": "产品评审会", "tagline": "欢迎参加产品评审会"})
            check(f"⑤ {label} 版式在白名单内（模型选版）", picked in LAYOUTS, picked)
            check(f"⑤ {label} 非敏感不被压成 minimal", picked != "minimal", picked)
    else:
        # 没配模型：走规则版
        check("⑤ 6 人 → focus", pick_layout({"is_sensitive": False, "attendees": ["a"] * 6}) == "focus")
        check("⑤ 2 人 → standard", pick_layout({"is_sensitive": False, "attendees": ["a", "b"]}) == "standard")

    # ⑥ 时段标牌：按会议室本地小时判定
    meeting = store.get_meeting("meeting_life")
    slot = scheduler.signage_slot(meeting)
    local_hour = to_local(now, meeting.timezone).hour
    expected = next(s["name"] for s in SIGNAGE_SLOTS if s["start_hour"] <= local_hour < s["end_hour"])
    check("⑥ 时段标牌按本地小时匹配", slot["name"] == expected, f"本地 {local_hour} 点 → {slot['name']}")

    # ⑦ REPLAY 带标牌地址
    payload = scheduler._replay_payload(meeting)
    check("⑦ REPLAY 带 signage_url", "signage_url" in payload and "slot=" in payload["signage_url"],
          payload["signage_url"])

    print("\n=== C/D 组冒烟 11 项全过：到期清理 + 标签 + 时段标牌 + 自动选版式 OK ===")


if __name__ == "__main__":
    main()

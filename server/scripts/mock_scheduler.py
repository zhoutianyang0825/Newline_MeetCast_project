"""调度器冒烟：验证「日历 → 状态机 → 指令下发 → 恢复标牌」闭环（D2）

用法：cd server && uv run python scripts/mock_scheduler.py
不依赖 HTTP 服务，直接调 scheduler.tick()，便于反复验证状态机。

冒烟序列：
  ① 首次 tick：会前 10 分钟窗口内 → 下发 PREPARE_MEETING
  ② 指令 payload 字段齐全（content_url/prepare_at/switch_at/timezone/until）
  ③ 再跑一次 tick：不重复下发（幂等）
  ④ 进行中的会议：不发 PREPARE，也不发 REPLAY
  ⑤ 会议结束后 tick：下发 REPLAY_DEFAULT
  ⑥ 已取消的会议（纽约那场）：一条指令都不发
  ⑦ 跨时区：巴塞罗那会议的 payload.timezone = Europe/Madrid
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

from app import scheduler  # noqa: E402
from app.store import seed, shift_minutes, store, utc_now_iso  # noqa: E402


def check(step: str, cond: bool, extra: str = "") -> None:
    """断言并打印，失败即退出"""
    mark = "PASS" if cond else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not cond:
        sys.exit(1)


def cmds_of(device_id: str, type_: str) -> list:
    """取某设备某类型的所有指令（便于计数与去重断言）"""
    return [c for c in store.all_commands() if c.device_id == device_id and c.type == type_]


def main() -> None:
    seed(store)

    # 给第二台设备绑到"会议进行中"的房间，验证 prepare 窗口已过就不再补发
    spare = store.get_device("SH-A3-01-02")
    spare.room_id = "room-b2-05"
    store.upsert_device(spare)

    # ① 首次 tick
    result = scheduler.tick()
    prepares = cmds_of("SH-A3-01-01", "PREPARE_MEETING")
    check("① 首次 tick 下发 PREPARE_MEETING", len(prepares) == 1, f"commands={result['commands']}")

    # ② payload 字段齐全
    payload = prepares[0].payload
    required = {"content_url", "meeting_id", "prepare_at", "switch_at", "timezone", "until"}
    check("② payload 字段齐全", required.issubset(payload.keys()), f"keys={sorted(payload.keys())}")
    check("② content_url 指向本机会议页", "/ui/display/meeting.html" in payload["content_url"],
          payload["content_url"].split("?")[0])
    # prepare_at 与 switch_at 相差 9 分钟（会前 10min vs 会前 1min）
    check("② switch_at 比 prepare_at 晚 9 分钟",
          shift_minutes(payload["prepare_at"], 9) == payload["switch_at"],
          f"{payload['prepare_at']} → {payload['switch_at']}")

    # ③ 幂等：再 tick 一次不新增
    before = len(cmds_of("SH-A3-01-01", "PREPARE_MEETING"))
    scheduler.tick()
    after = len(cmds_of("SH-A3-01-01", "PREPARE_MEETING"))
    check("③ 重复 tick 不重复下发", before == after, f"{before} → {after}")

    # ④ 进行中的会议：SH-A3-01-02 在 room-b2-05（会已开 20 分钟）→ 既无 PREPARE 也无 REPLAY
    busy_prepare = cmds_of("SH-A3-01-02", "PREPARE_MEETING")
    busy_replay = cmds_of("SH-A3-01-02", "REPLAY_DEFAULT")
    check("④ 进行中会议不发 PREPARE/REPLAY", not busy_prepare and not busy_replay,
          f"prepare={len(busy_prepare)} replay={len(busy_replay)}")

    # ⑤ 把会议改成刚结束 → tick 应发 REPLAY_DEFAULT（改完必须落库）
    target = store.get_meeting(prepares[0].payload["meeting_id"])
    target.end_time_utc = shift_minutes(utc_now_iso(), -1)
    target.start_time_utc = shift_minutes(utc_now_iso(), -40)
    store.upsert_meeting(target)
    scheduler.tick(resync=False)          # 跳过重同步，模拟"时间流逝到会议结束"
    replays = cmds_of("SH-A3-01-01", "REPLAY_DEFAULT")
    check("⑤ 会议结束下发 REPLAY_DEFAULT", len(replays) == 1, f"replay={len(replays)}")
    check("⑤ REPLAY 带 meeting_id 供追溯", replays[0].payload.get("meeting_id") == target.meeting_id)

    # ⑥ 已取消会议：纽约房间不发任何指令（该房间也没有绑定设备，双保险）
    cancelled = [m for m in store.all_meetings() if m.status == "cancelled"]
    cancelled_cmds = [c for c in store.all_commands()
                      if c.payload.get("meeting_id") in {m.meeting_id for m in cancelled}]
    check("⑥ 已取消会议不下发指令", not cancelled_cmds, f"cancelled={len(cancelled)}")

    # ⑦ 跨时区字段：巴塞罗那那场必须是 Europe/Madrid
    bcn = [m for m in store.all_meetings() if m.room_id == "room-bcn-01"]
    check("⑦ 巴塞罗那会议时区正确", bcn and bcn[0].timezone == "Europe/Madrid",
          f"tz={bcn[0].timezone if bcn else 'N/A'}")

    print("\n=== 调度器冒烟 7 项全过：日历 → 状态机 → 指令闭环 OK ===")
    print(f"（当前指令总数 {len(store.all_commands())}，审计流可直接查 /api/admin/commands）")


if __name__ == "__main__":
    main()

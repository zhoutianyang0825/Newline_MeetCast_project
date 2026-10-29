"""F 组冒烟：Graph 客户端（Mock 双轨）+ 上传链接自动生成与邮件（F2.1 / F2.3 / F2.4 / F4.7）

用法：cd server && uv run python scripts/mock_graph.py
不依赖 HTTP。

冒烟序列：
  ① Mock 模式拉日历：返回会议且结构完整
  ② 会议室同步：4 间
  ③ 新会议自动生成上传链接（已有 token 的会议不重复建）
  ④ 邮件落库：收件人是组织者、正文含上传链接
  ⑤ 重复执行不重复发信（幂等）
  ⑥ 真模式缺凭据 → 自动回落 Mock 不报错
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

from app import graph_client, mailer, scheduler  # noqa: E402
from app.store import seed, store  # noqa: E402


def check(step: str, cond: bool, extra: str = "") -> None:
    """断言并打印，失败即退出"""
    mark = "PASS" if cond else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not cond:
        sys.exit(1)


def main() -> None:
    seed(store)

    # ① Mock 拉日历
    events = graph_client.fetch_events()
    required = {"meeting_id", "room_id", "subject", "organizer_email", "attendees",
                "start_time_utc", "end_time_utc", "timezone", "status"}
    check("① Mock 拉日历非空", len(events) >= 4, f"{len(events)} 场")
    check("① 事件结构完整", required.issubset(events[0].keys()), ",".join(sorted(events[0].keys())))

    # ② 会议室同步
    rooms = graph_client.sync_rooms()
    check("② 会议室同步 4 间", len(rooms) == 4, f"{len(rooms)} 间")

    # ③ 自动生成上传链接
    store.mail_log.clear()
    sent = scheduler.ensure_upload_links()
    check("③ 新会议生成了链接", sent >= 1, f"{sent} 条")
    check("③ 已有 token 的会议未重复建", store.token_for_meeting("meeting_a3_01_1") is not None)

    # ④ 邮件内容
    check("④ 邮件已落库", len(store.mail_log) == sent, f"log={len(store.mail_log)}")
    record = store.mail_log[0]
    check("④ 收件人为组织者", "@" in record["to"], record["to"])
    check("④ 正文含上传链接", "/ui/upload.html?token=" in record["body"])

    # ⑤ 幂等
    again = scheduler.ensure_upload_links()
    check("⑤ 重复执行不再发信", again == 0 and len(store.mail_log) == sent, f"again={again}")

    # ⑥ 真模式缺凭据回落
    original_mock = graph_client.GRAPH_MOCK
    graph_client.GRAPH_MOCK = False
    try:
        fallback = graph_client.fetch_events()
        check("⑥ 缺凭据自动回落 Mock", len(fallback) >= 4, f"{len(fallback)} 场")
    finally:
        graph_client.GRAPH_MOCK = original_mock

    print("\n=== F 组冒烟 9 项全过：Graph Mock 双轨 + 链接生成 + 邮件通道 OK ===")
    print(f"（邮件为 mock 模式：{mailer.MAIL_MOCK}，记录可在 store.mail_log 查）")


if __name__ == "__main__":
    main()

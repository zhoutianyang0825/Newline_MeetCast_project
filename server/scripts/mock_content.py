"""A 组冒烟：会议页内容生成 + 敏感脱敏（F5.1~F5.5）

用法：cd server && uv run python scripts/mock_content.py
不依赖 HTTP，直接调 content 模块。

冒烟序列：
  ① 普通会议：标题用原文、文案来源与本机配置一致
     （配了 LLM key → degraded=llm；没配 → degraded=template）
  ② 参会人 / 组织者 / 时间 / 时区偏移都算出来了
  ③ 敏感会议：标题变「会议中」、degraded=sensitive
  ④ 敏感会议的真实标题不出现在任何字段里（含 content_url）
  ⑤ 黑名单逐个命中验证（薪酬/绩效/面试/裁员…）
  ⑥ 本地时间换算正确：上海 02:00Z → 10:00
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

from app import llm, scheduler  # noqa: E402
from app.content import MASKED_TITLE, SENSITIVE_KEYWORDS, build_meeting_content, is_sensitive  # noqa: E402
from app.store import Meeting, seed, shift_minutes, store, utc_now_iso  # noqa: E402
from app.tz import local_hm  # noqa: E402

ROOM_TZ = "Asia/Shanghai"


def check(step: str, cond: bool, extra: str = "") -> None:
    """断言并打印，失败即退出"""
    mark = "PASS" if cond else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not cond:
        sys.exit(1)


def make_meeting(subject: str, start_offset_min: int = 30) -> Meeting:
    """造一场会议（用于敏感/普通两路对比）"""
    now = utc_now_iso()
    return Meeting(
        meeting_id="meeting_test",
        room_id="room-a3-01",
        subject=subject,
        organizer_email="zhangsan@honghe.com",
        attendees=["张三", "李四", "王五", "赵六", "钱七", "孙八"],
        start_time_utc=shift_minutes(now, start_offset_min),
        end_time_utc=shift_minutes(now, start_offset_min + 60),
        timezone=ROOM_TZ,
    )


def main() -> None:
    seed(store)

    # ① 普通会议
    normal = make_meeting("产品评审会")
    content = build_meeting_content(normal)
    check("① 普通会议标题用原文", content["title"] == "产品评审会")
    # 文案来源取决于本机有没有配 LLM key：两种都算正常，只断言"与配置一致"
    expect_degraded = "llm" if llm.available() else "template"
    check(f"① 文案来源与配置一致（{expect_degraded}）",
          content["degraded"] == expect_degraded, f"tagline={content['tagline']}")
    check("① 文案非空且长度合理", 4 <= len(content["tagline"]) <= 60, content["tagline"])

    # ② 字段完整性
    check("② 参会人 6 人", len(content["attendees"]) == 6)
    check("② 组织者取邮箱前缀", content["organizer"] == "zhangsan")
    check("② 时间已本地化（含连接符）", "–" in content["time_label"], content["time_label"])
    check("② 时区偏移为 +08:00", content["utc_offset"] == "+08:00", content["utc_offset"])

    # ③ 敏感会议
    secret = make_meeting("薪酬方案讨论")
    # 敏感会议绝不能调模型：把 chat_json 换成计数桩，构建完断言调用次数为 0
    calls = {"n": 0}
    real_chat_json = llm.chat_json

    def counting_stub(*args, **kwargs):
        calls["n"] += 1
        return real_chat_json(*args, **kwargs)

    llm.chat_json = counting_stub
    try:
        masked = build_meeting_content(secret)
    finally:
        llm.chat_json = real_chat_json
    check("③ 敏感会议不调用模型", calls["n"] == 0, f"chat_json 调用 {calls['n']} 次")
    check("③ 敏感会议标题脱敏", masked["title"] == MASKED_TITLE, masked["title"])
    check("③ 降级原因标记为 sensitive", masked["degraded"] == "sensitive")

    # ④ 真实标题不得出现在任何字段 / URL 里
    dumped = json.dumps(masked, ensure_ascii=False)
    check("④ 内容里无真实标题", "薪酬" not in dumped)
    url = scheduler.content_url_of(secret)
    check("④ content_url 里无真实标题", "薪酬" not in unquote(url), "URL 已脱敏")
    check("④ content_url 的 subject 为「会议中」", f"subject={MASKED_TITLE}" in unquote(url))

    # ⑤ 黑名单逐个命中
    missed = [kw for kw in SENSITIVE_KEYWORDS if not is_sensitive(f"{kw}相关会议")]
    check("⑤ 黑名单全部命中", not missed, f"漏判={missed}")

    # ⑥ 本地时间换算：上海 02:00Z → 10:00
    check("⑥ 02:00Z 在上海是 10:00", local_hm("2026-10-27T02:00:00Z", ROOM_TZ) == "10:00",
          local_hm("2026-10-27T02:00:00Z", ROOM_TZ))

    print(f"\n=== A 组冒烟全过：内容生成 + 敏感脱敏 + 本地时间 OK（文案来源={('llm' if llm.available() else 'template')}）===")


if __name__ == "__main__":
    main()

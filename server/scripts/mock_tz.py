"""B 组冒烟：时区 / 夏令时换算（F2.5，PRD 验收硬指标）

用法：cd server && uv run python scripts/mock_tz.py

覆盖矩阵（全部用 zoneinfo 真规则，不手工加减）：
  ① 纽约冬令时（EST, -05:00）
  ② 纽约夏令时（EDT, -04:00）
  ③ 巴塞罗那冬令时（CET, +01:00）
  ④ 巴塞罗那夏令时（CEST, +02:00）
  ⑤ 正常期间：纽约 ↔ 巴塞罗那 时差 6 小时
  ⑥ 错位窗口 1（美国已切换、欧盟未切换，3/8~3/29）时差 5 小时
  ⑦ 错位窗口 2（欧盟已回拨、美国未回拨，10/25~11/1）时差 5 小时
  ⑧ 美国切换日边界：2026-03-08 07:00Z 起纽约变 -04:00
  ⑨ 欧盟回拨日边界：2026-10-25 01:00Z 起马德里变 +01:00
  ⑩ 跨切换时刻的会议：起止偏移不同（-04:00 → -05:00）
  ⑪ 会议时间标签按会议室本地时区输出
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

from app.tz import local_hm, local_time_range, to_local, utc_offset_label  # noqa: E402

NY = "America/New_York"
BCN = "Europe/Madrid"
SH = "Asia/Shanghai"


def check(step: str, cond: bool, extra: str = "") -> None:
    """断言并打印，失败即退出"""
    mark = "PASS" if cond else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not cond:
        sys.exit(1)


def hours_between(iso_a: str, tz_a: str, iso_b: str, tz_b: str) -> float:
    """两个本地时间的时差（小时，带符号）"""
    local_a = to_local(iso_a, tz_a)
    local_b = to_local(iso_b, tz_b)
    return (local_b.replace(tzinfo=None) - local_a.replace(tzinfo=None)) / timedelta(hours=1)


def main() -> None:
    # ① ② 纽约冬/夏令时
    check("① 纽约 1 月为 EST -05:00", utc_offset_label("2026-01-15T14:00:00Z", NY) == "-05:00",
          utc_offset_label("2026-01-15T14:00:00Z", NY))
    check("② 纽约 7 月为 EDT -04:00", utc_offset_label("2026-07-15T13:00:00Z", NY) == "-04:00",
          utc_offset_label("2026-07-15T13:00:00Z", NY))

    # ③ ④ 巴塞罗那冬/夏令时
    check("③ 马德里 1 月为 CET +01:00", utc_offset_label("2026-01-15T08:00:00Z", BCN) == "+01:00",
          utc_offset_label("2026-01-15T08:00:00Z", BCN))
    check("④ 马德里 7 月为 CEST +02:00", utc_offset_label("2026-07-15T07:00:00Z", BCN) == "+02:00",
          utc_offset_label("2026-07-15T07:00:00Z", BCN))

    # ⑤ 正常期间 6 小时（同样的 UTC 时刻，两地本地时间差 6h）
    normal = hours_between("2026-01-15T14:00:00Z", NY, "2026-01-15T14:00:00Z", BCN)
    check("⑤ 正常期间时差 6 小时", normal == 6, f"{normal}h")

    # ⑥ 错位窗口 1：2026-03-10（美国 3/8 已切、欧盟 3/29 才切）
    window1 = hours_between("2026-03-10T13:00:00Z", NY, "2026-03-10T13:00:00Z", BCN)
    check("⑥ 错位窗口 1 时差 5 小时", window1 == 5, f"{window1}h")

    # ⑦ 错位窗口 2：2026-10-27（欧盟 10/25 已回拨、美国 11/1 才回拨）
    window2 = hours_between("2026-10-27T12:00:00Z", NY, "2026-10-27T12:00:00Z", BCN)
    check("⑦ 错位窗口 2 时差 5 小时", window2 == 5, f"{window2}h")

    # ⑧ 美国切换日边界：07:00Z 之前 -05:00，之后 -04:00
    before = utc_offset_label("2026-03-08T06:59:00Z", NY)
    after = utc_offset_label("2026-03-08T07:00:00Z", NY)
    check("⑧ 纽约 3/8 切换边界", before == "-05:00" and after == "-04:00", f"{before} → {after}")

    # ⑨ 欧盟回拨边界：01:00Z 之前 +02:00，之后 +01:00
    before_eu = utc_offset_label("2026-10-25T00:59:00Z", BCN)
    after_eu = utc_offset_label("2026-10-25T01:00:00Z", BCN)
    check("⑨ 马德里 10/25 回拨边界", before_eu == "+02:00" and after_eu == "+01:00", f"{before_eu} → {after_eu}")

    # ⑩ 跨切换时刻的会议：起 -04:00、止 -05:00（本地显示 01:00 – 02:00，实际过了 2 小时）
    start_off = utc_offset_label("2026-11-01T05:00:00Z", NY)
    end_off = utc_offset_label("2026-11-01T07:00:00Z", NY)
    label = local_time_range("2026-11-01T05:00:00Z", "2026-11-01T07:00:00Z", NY)
    check("⑩ 跨切换会议起止偏移不同", start_off == "-04:00" and end_off == "-05:00", f"{start_off} → {end_off}")
    check("⑩ 跨切换会议本地标签", label == "01:00 – 02:00", label)

    # ⑪ 本地时间标签（上海 02:00Z → 10:00）
    check("⑪ 上海本地时间标签", local_time_range("2026-10-27T02:00:00Z", "2026-10-27T03:00:00Z", SH) == "10:00 – 11:00",
          local_hm("2026-10-27T02:00:00Z", SH))

    print("\n=== B 组冒烟 11 项全过：美欧 DST 切换日 + 两段错位窗口 + 跨切换会议 OK ===")


if __name__ == "__main__":
    main()

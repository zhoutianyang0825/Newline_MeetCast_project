"""一键跑全部冒烟（唯一入口，不用再记 4 个脚本）

用法：
  cd server
  uv run python scripts/run_all_smoke.py            # 全跑（需先启动服务）
  uv run python scripts/run_all_smoke.py --skip-http # 只跑不依赖 HTTP 的（调度器）

包含：
  1. mock_scheduler   调度器状态机（不起服务也能跑）
  2. mock_device      设备端基础 3 接口（poll/ack/heartbeat，需要服务）
  3. mock_device_extra 设备端扩展 3 接口（profile/schedule/materials，需要服务）
  4. mock_admin       管理端设备 3 接口（需要服务）
  5. mock_admin_extra 素材/上传/日历/运维 10 接口（需要服务）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SUITES = [
    ("调度器状态机", "mock_scheduler.py", False),
    ("会议页内容生成", "mock_content.py", False),
    ("时区/DST 换算", "mock_tz.py", False),
    ("素材生命周期/版式", "mock_lifecycle.py", False),
    ("Graph Mock/邮件", "mock_graph.py", False),
    ("LLM 文案/选版式", "mock_llm.py", False),
    ("账号与角色", "mock_auth.py", False),
    ("设备端 3 接口", "mock_device.py", True),
    ("设备端档案/日程/素材", "mock_device_extra.py", True),
    ("管理端设备 3 接口", "mock_admin.py", True),
    ("素材/上传/日历/运维", "mock_admin_extra.py", True),
    ("二维码/分类/大屏参数", "mock_p0_gap.py", True),
]


def main() -> None:
    """按顺序跑各套冒烟，任一套失败立即中止。

    得到的数据：
        命令行参数（可选 "--skip-http"，跳过依赖服务的 HTTP 用例）。

    要做的操作：
        逐个 subprocess 调用同目录的冒烟脚本，透传输出；
        返回码非 0 即中止，并打印失败的那一套。

    返回：
        无（失败时 sys.exit(1)）。

    为什么：回归只需要记一个命令，避免"该跑哪个"的混乱。
    """
    skip_http = "--skip-http" in sys.argv
    failed: list[str] = []

    for title, filename, needs_http in SUITES:
        if skip_http and needs_http:
            print(f"\n===== 跳过 {title}（--skip-http）=====")
            continue
        print(f"\n===== {title} · {filename} =====")
        result = subprocess.run([sys.executable, str(SCRIPTS_DIR / filename)], cwd=str(SCRIPTS_DIR.parent))
        if result.returncode != 0:
            failed.append(f"{title}（{filename}）")
            break

    if failed:
        print(f"\n❌ 冒烟失败：{failed[0]}")
        sys.exit(1)
    print("\n✅ 全部冒烟通过")


if __name__ == "__main__":
    main()

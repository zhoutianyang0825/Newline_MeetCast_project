"""LLM 接入冒烟（F5.1 文案 / F3.5 选版式）

用法：cd server && uv run python scripts/mock_llm.py
依赖：会自己拉起 scripts/mock_llm_server.py（本地假网关，不需要真 Key）

序列：
  ① 未配 Key                → degraded=template（不调模型，功能不坏）
  ② 配 Key + 正常网关       → degraded=llm，文案来自模型
  ③ 网关 500                → 自动降级 template（不抛错、不空屏）
  ④ 敏感会议 + 正常网关     → degraded=sensitive，且**模型一次都没被调用**
  ⑤ 选版式：模型可用        → 采用模型选择（focus）
  ⑥ 选版式：模型不可用      → 规则兜底（5 人 standard / 6 人 focus）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from _smoke_db import use_fresh_smoke_db  # noqa: E402

use_fresh_smoke_db()  # 一次性冒烟库：清旧文件 + 切 env（必须在 import app 之前）

PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"

# 子进程里执行的探针：构造会议 → 生成内容 → 选版式 → 打印 JSON
PROBE = """
import json
from app.content import build_meeting_content
from app.layouts import pick_layout
from app.store import Meeting

meeting = Meeting(
    meeting_id="m_probe",
    room_id="room-a3-01",
    subject={subject!r},
    organizer_email="zhangsan@honghe.com",
    start_time_utc="2026-10-27T02:00:00Z",
    end_time_utc="2026-10-27T03:00:00Z",
    attendees={attendees!r},
    timezone="Asia/Shanghai",
)
content = build_meeting_content(meeting)
content["layout"] = pick_layout(content)
print(json.dumps(content, ensure_ascii=False))
"""


def check(step: str, ok: bool, extra: str = "") -> None:
    """断言布尔条件并打印，失败即退出。"""
    mark = "PASS" if ok else "FAIL"
    suffix = f"  {extra}" if extra else ""
    print(f"[{mark}] {step}{suffix}")
    if not ok:
        sys.exit(1)


def probe(subject: str, attendees: list[str], env_extra: dict) -> dict:
    """在干净子进程里跑一次内容生成，返回结果字典。

    得到的数据：
        subject（会议标题）；attendees（参会人）；
        env_extra（要覆盖的环境变量，如 LLM 网关地址）。

    要做的操作：
        用当前解释器 -c 执行 PROBE 代码，合并环境变量并捕获 stdout。

    返回：
        {"title": ..., "tagline": ..., "degraded": ..., "layout": ...}

    为什么：LLM 配置与模块状态在 import 时确定，必须在独立进程里验证不同配置，
            否则一轮进程只能测一种情况。
    """
    env = {**os.environ, **env_extra}
    code = PROBE.format(subject=subject, attendees=attendees)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(SERVER_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr[-800:])
        raise RuntimeError("探针执行失败")
    line = [ln for ln in result.stdout.strip().splitlines() if ln.startswith("{")][-1]
    return json.loads(line)


def wait_mock(timeout: float = 8.0) -> bool:
    """等待假网关就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/stats", timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:                      # noqa: BLE001 - 还没起来，继续等
            time.sleep(0.2)
    return False


def stats() -> dict:
    """读假网关的请求计数。"""
    with urllib.request.urlopen(f"{BASE}/stats", timeout=2) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    mock = subprocess.Popen(
        [sys.executable, str(SERVER_DIR / "scripts" / "mock_llm_server.py"), "--port", str(PORT)],
        cwd=str(SERVER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_mock():
            raise RuntimeError("假网关未能在 8 秒内启动")
        print(f"[mock] 假网关就绪：{BASE}")

        normal_env = {
            "MEETCAST_LLM_BASE_URL": f"{BASE}/v1",
            "MEETCAST_LLM_API_KEY": "mock-key",
            "MEETCAST_LLM_MODEL": "mock-model",
            "MEETCAST_LLM_TIMEOUT": "3",
        }
        fail_env = {**normal_env, "MEETCAST_LLM_BASE_URL": f"{BASE}/v1fail"}
        no_key_env = {**normal_env, "MEETCAST_LLM_API_KEY": ""}

        # ① 无 Key → 模板降级
        r = probe("产品评审会", ["张三", "李四"], no_key_env)
        check("① 无 Key → template", r["degraded"] == "template", f"tagline={r['tagline']}")

        # ② 正常网关 → LLM 文案
        r = probe("产品评审会", ["张三", "李四"], normal_env)
        check("② 正常网关 → llm", r["degraded"] == "llm", f"tagline={r['tagline']}")
        check("② 文案来自模型", "议程已就绪" in r["tagline"], r["tagline"])

        # ③ 网关 500 → 降级模板，不抛错
        r = probe("产品评审会", ["张三", "李四"], fail_env)
        check("③ 网关异常 → template", r["degraded"] == "template", f"tagline={r['tagline']}")

        # ④ 敏感会议 → 跳过模型（对比调用计数）
        before = stats()["total"]
        r = probe("薪酬方案讨论", ["张三", "李四"], normal_env)
        after = stats()["total"]
        check("④ 敏感会议脱敏", r["degraded"] == "sensitive" and r["title"] == "会议中", f"title={r['title']}")
        check("④ 敏感会议未调用模型", before == after, f"请求数 {before} → {after}")

        # ⑤ 选版式：模型可用 → 采用模型结果（focus）
        r = probe("产品评审会", ["张三", "李四"], normal_env)
        check("⑤ 模型选版 → focus", r["layout"] == "focus", f"layout={r['layout']}")

        # ⑥ 选版式：模型不可用 → 规则兜底
        r5 = probe("产品评审会", ["张三", "李四", "王五", "赵六", "钱七"], no_key_env)
        r6 = probe("产品评审会", ["张三", "李四", "王五", "赵六", "钱七", "孙八"], no_key_env)
        check("⑥ 5 人 → standard", r5["layout"] == "standard", f"layout={r5['layout']}")
        check("⑥ 6 人 → focus", r6["layout"] == "focus", f"layout={r6['layout']}")

        s = stats()
        print(f"\n[mock] 累计请求：copy={s['copy']} layout={s['layout']} total={s['total']}")
        print("LLM 接入冒烟 6 组全过：调用 / 解析 / 降级 / 敏感隔离 / 选版 都覆盖")
    finally:
        mock.terminate()
        try:
            mock.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock.kill()


if __name__ == "__main__":
    main()

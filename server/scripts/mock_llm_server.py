"""假 LLM 网关：用于验证"接 AI"的调用链，不需要真实 Key。

用法：
    python scripts/mock_llm_server.py --port 8899

提供两个前缀（同一进程内切换正常/故障）：
    /v1/chat/completions       → 正常返回 JSON（文案 / 版式按请求内容自动识别）
    /v1fail/chat/completions   → 恒定 500（验证"LLM 挂了要降级"）
    GET /stats                 → {"copy": n, "layout": n, "total": n} 请求计数

为什么需要它：
    真实 Key 不能进代码库，而"没有 Key 就不验证"等于把所有 LLM 相关代码都变成未测状态。
    用一个本地假网关，就能把"调用 → 解析 → 校验 → 降级"整条链路测干净。
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 请求计数：冒烟脚本用它断言"敏感会议根本没发请求"
STATE = {"copy": 0, "layout": 0, "total": 0}

# 文案请求的识别特征与固定回复
COPY_MARK = "tagline"
LAYOUT_MARK = "可选版式"


class Handler(BaseHTTPRequestHandler):
    """最小可用的 OpenAI 兼容端点。"""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        if self.path.rstrip("/") == "/stats":
            self._json(200, STATE)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"

        # 故障模式：验证降级链
        if self.path.startswith("/v1fail"):
            self._json(500, {"error": {"message": "mock failure"}})
            return

        try:
            payload = json.loads(raw)
            user_text = payload["messages"][-1]["content"]
        except (json.JSONDecodeError, KeyError, IndexError):
            self._json(400, {"error": {"message": "bad request"}})
            return

        if LAYOUT_MARK in user_text:
            STATE["layout"] += 1
            STATE["total"] += 1
            reply = {"layout": "focus", "reason": "参会人较多，聚焦版更醒目"}
        elif COPY_MARK in user_text:
            STATE["copy"] += 1
            STATE["total"] += 1
            reply = {"tagline": "议程已就绪，欢迎各位入座"}
        else:
            STATE["total"] += 1
            reply = {"tagline": "（mock 未识别请求类型）"}

        self._json(200, {
            "id": "mock-1",
            "object": "chat.completion",
            "model": payload.get("model", "mock"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        """静默访问日志，避免刷屏。"""
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[mock-llm] 监听 http://127.0.0.1:{args.port}/v1/chat/completions")
    print(f"[mock-llm] 故障模式 http://127.0.0.1:{args.port}/v1fail/chat/completions")
    server.serve_forever()


if __name__ == "__main__":
    main()

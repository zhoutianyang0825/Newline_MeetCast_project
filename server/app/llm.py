"""LLM 调用（F5.1 会议页文案 / F3.5 智能选版式）

协议：OpenAI 兼容 `/chat/completions`——DeepSeek、阿里百炼、vLLM、Ollama 都能直接换。

铁律：**任何异常都返回 None**。调用方必须能在拿不到结果时降级，
      LLM 是加分项，绝不能变成单点故障（PRD F5.4 的降级顺序就是这个意思）。
"""

from __future__ import annotations

import json
import time

import httpx

from app.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SEC


def available() -> bool:
    """是否配好了 LLM 凭据。

    得到的数据：
        无。

    要做的操作：
        看 settings 里 LLM_API_KEY 是否为空。

    返回：
        True（可调用）/ False（未配置，调用方直接走模板）。

    为什么：没配 key 时不该每场会都发一次注定失败的请求——先问一句最省事。
    """
    return bool(LLM_API_KEY)


def model_label() -> str:
    """当前模型与网关的可读标识（日志/健康检查用）。

    得到的数据：
        无。

    要做的操作：
        拼 "deepseek-chat @ https://api.deepseek.com/v1"。

    返回：
        字符串。

    为什么：排障时第一眼看的就是"到底调的哪个模型、哪个网关"。
    """
    return f"{LLM_MODEL} @ {LLM_BASE_URL}"


def chat_json(system: str, user: str, *, max_tokens: int = 220, purpose: str = "llm") -> dict | None:
    """让模型输出一个 JSON 对象，失败一律返回 None。

    得到的数据：
        system（角色约束，如"你是会议屏文案助手，只输出 JSON"）；
        user（本次任务描述 + 会议信息）；
        max_tokens（输出上限，文案场景 200 足够）；
        purpose（日志标签，如 "copy" / "layout"）。

    要做的操作：
        t1 未配置密钥 → 直接 None（不发请求）；
        t2 POST /chat/completions，要求 response_format=json_object；
        t3 若网关不支持该参数（400）→ 去掉后重试一次；
        t4 从 choices[0].message.content 里抠 JSON（兼容 ```json 包裹）；
        t5 任何异常/超时/解析失败 → 打印一行原因并返回 None。

    返回：
        {"tagline": "..."} / {"layout": "focus"} 之类的字典；失败为 None。

    为什么：模型输出不是可靠数据结构，必须"宽进严出"——
            解析失败就当作没生成，让模板兜住，屏幕永远不会因为模型抽风而空白。
    """
    if not available():
        return None

    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload: dict = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.6,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    started = time.perf_counter()

    try:
        with httpx.Client(timeout=LLM_TIMEOUT_SEC) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 400:
                # 部分兼容网关不认 response_format，去掉再试一次（其余错误不重试）
                payload.pop("response_format", None)
                resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()

        content = body["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        cost_ms = int((time.perf_counter() - started) * 1000)
        if parsed is None:
            print(f"[llm] {purpose} 返回非 JSON（{cost_ms}ms），走降级")
            return None
        print(f"[llm] {purpose} ok {cost_ms}ms model={LLM_MODEL}")
        return parsed
    except Exception as exc:                      # noqa: BLE001 - 任何异常都必须降级
        cost_ms = int((time.perf_counter() - started) * 1000)
        print(f"[llm] {purpose} 失败 {cost_ms}ms：{type(exc).__name__}: {exc}")
        return None


def _extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON 对象。

    得到的数据：
        text（模型原始输出，可能是纯 JSON、```json 包裹、或前后带废话）。

    要做的操作：
        t1 去空白；t2 若有 ``` 代码块则取块内内容并去掉语言标记；
        t3 直接 json.loads；失败则截取第一个 { 到最后一个 } 再试一次。

    返回：
        解析成功的 dict；实在解析不出来返回 None。

    为什么：即使要求了 json_object，不同网关仍可能给 ```json 包裹或加解释文字，
             这里做一次性清洗比在业务代码里到处 try/except 干净。
    """
    text = (text or "").strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lower().startswith("json"):
                text = text[4:]
    text = text.strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None

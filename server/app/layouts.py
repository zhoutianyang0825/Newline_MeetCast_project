"""固定版式与自动选版（F3.5 / F4.3）

人工不选模版，由 LLM 按内容挑；模型不可用/拿不准时回落规则，最终永远有 `standard` 兜底。
敏感会议**不走模型**，直接 `minimal`——这是硬约束，不能交给概率。
`minimal` 因此只属于敏感会议：普通会议的候选集只有 `standard / focus`。
"""

from __future__ import annotations

from app import llm

# 三套固定版式（F4.3：2~3 个可靠版式）
LAYOUTS: dict[str, dict] = {
    "standard": {
        "label": "标准版",
        "desc": "标题 + 时间 + 组织者 + 参会人，通用场景",
        "page": "/ui/display/meeting.html",
    },
    "focus": {
        "label": "聚焦版",
        "desc": "大标题优先、参会人折叠成头像条，适合 6 人以上大会",
        "page": "/ui/display/meeting.html?layout=focus",
    },
    "minimal": {
        "label": "极简版",
        "desc": "只显示「会议中」，不展示任何会议细节（敏感会议专用）",
        "page": "/ui/display/meeting.html?layout=minimal",
    },
}

# 参会人数达到多少用聚焦版（LLM 不可用时的规则依据）
FOCUS_THRESHOLD = 6

# 允许模型在**非敏感**会议里挑的版式。
# minimal 不在其中：它是"只显示会议中、不展示任何细节"的敏感专用版，
# 一旦让模型选它，普通会议的信息就会被整个藏掉（实测模型真会这么选）。
LLM_CANDIDATES = ("standard", "focus")


def _llm_pick(content: dict) -> str | None:
    """让模型在候选版式里挑一个。

    得到的数据：
        content（build_meeting_content 的产出：title / tagline / attendees 等）。

    要做的操作：
        t1 未配置 LLM → None；
        t2 把标题、人数、文案、**两个候选版式**（standard / focus）给模型，
           要求输出 {"layout": "...", "reason": "..."}；
        t3 只接受 LLM_CANDIDATES 里的版式名，其余（含 minimal、乱造的名字）一律 None。

    返回：
        "standard" / "focus"；不可用或数据不合法为 None。

    为什么：版式选择是"语义判断"（这场会偏正式还是偏轻松、人多人少观感如何），
            正是模型擅长的模糊决策；但候选集必须收窄 + 输出白名单校验——
            minimal 属于敏感会议的硬规则，不能变成模型的自由选项。
    """
    if not llm.available():
        return None

    system = "你是会议室大屏版式选择器。只输出 JSON，不要解释。"
    user = (
        f"会议标题：{content.get('title')}\n"
        f"引导语：{content.get('tagline')}\n"
        f"参会人数：{len(content.get('attendees', []))}\n"
        f"会议时段：{content.get('time_label')}\n\n"
        "可选版式：\n"
        "- standard：标题+时间+组织者+参会人，通用\n"
        "- focus：大标题优先、参会人折叠，适合人数多（≥6）或标题较长的会\n\n"
        '请选一个最合适的，输出：{"layout": "standard|focus", "reason": "一句话理由"}'
    )
    data = llm.chat_json(system, user, max_tokens=80, purpose="layout")
    layout = (data or {}).get("layout")
    if isinstance(layout, str) and layout.strip() in LLM_CANDIDATES:
        return layout.strip()
    return None


def pick_layout(content: dict) -> str:
    """按内容自动选版式（LLM 优先，规则兜底）。

    得到的数据：
        content（build_meeting_content 的产出，至少含 is_sensitive / attendees）。

    要做的操作：
        t1 敏感会议 → minimal（硬约束，不问模型，任何细节都不展示）；
        t2 非敏感 → 试 LLM 在 standard/focus 里选，命中候选集则采用；
        t3 模型不可用/答非所问 → 规则：参会人 ≥6 用 focus，其余 standard。

    返回：
        "minimal"（仅敏感）/ "focus" / "standard"

    为什么：模型挂了屏幕还得照常显示，所以永远有一条确定性兜底路径；
            而敏感会议连"让模型看一眼标题"的机会都不给（F5.5 的隔离要求）。
    """
    if content.get("is_sensitive"):
        return "minimal"

    llm_choice = _llm_pick(content)
    if llm_choice:
        return llm_choice

    if len(content.get("attendees", [])) >= FOCUS_THRESHOLD:
        return "focus"
    return "standard"


def layout_page(layout: str) -> str:
    """版式 → 页面路径（拼 content_url 用）。

    得到的数据：
        layout（版式名，如 "focus"）。

    要做的操作：
        查 LAYOUTS 取 page；未知版式回落到 standard。

    返回：
        "/ui/display/meeting.html?layout=focus"

    为什么：设备只负责打开 URL，版式差异全部体现在页面上，换版式无须改设备。
    """
    return LAYOUTS.get(layout, LAYOUTS["standard"])["page"]

"""会议页内容生成（F5.1~F5.5）

降级顺序固定（PRD F5.4）：**先过敏感判定 → 再走 LLM → LLM 失败才降纯文字标题**。
敏感会议（命中黑名单）任何路径都不出现真实标题，标题一律显示「会议中」。

LLM 走 app/llm.py（OpenAI 兼容协议）；未配 key 或调用失败时自动回落模板文案——
所以"有没有 AI"只影响文案质量，不影响屏幕能否正常出内容。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app import llm
from app.tz import local_time_range, utc_offset_label

# 仅类型检查期引用 Meeting：运行时不 import store，避免 store ↔ content 循环导入
if TYPE_CHECKING:
    from app.store import Meeting
# 敏感词黑名单（F5.5）：命中即脱敏，跳过一切生成逻辑
SENSITIVE_KEYWORDS = (
    "薪酬", "绩效", "工资", "调薪", "面试", "裁员", "离职",
    "并购", "融资", "报价", "竞标", "诉讼", "舆情",
)

# 品牌资产（PRD 定稿：白 + 紫 #7C3AED + 深紫 #4C1D95，Logo 用图标版）
BRAND = {
    "logo": "/ui/assets/brand/logo_icon.svg",
    "primary": "#7C3AED",
    "deep": "#4C1D95",
    "theme": "light",
}

# 敏感会议的统一替代文案
MASKED_TITLE = "会议中"
MASKED_TAGLINE = "内部会议进行中"


def is_sensitive(subject: str) -> bool:
    """标题是否命中敏感词。

    得到的数据：
        subject（会议标题，如 "薪酬方案讨论"）。

    要做的操作：
        逐个关键词做子串匹配（本期用最朴素的包含判定）。

    返回：
        True（命中，需脱敏）/ False（不敏感）。

    为什么：敏感判定必须前置，否则"降级反而把敏感标题暴露出来"（PRD F5.4）。
    """
    return any(keyword in subject for keyword in SENSITIVE_KEYWORDS)


def _template_copy(meeting: Meeting, attendee_count: int) -> str:
    """模板文案（无 LLM 时的默认产出）。

    得到的数据：
        meeting（会议行）；attendee_count（参会人数）。

    要做的操作：
        按"人数 + 时段"套一句固定句式。

    返回：
        "6 位同事已就位，议程加载完毕"（示例）

    为什么：LLM 未接入时也要有像样的文案；同时它是 LLM 失败后的第一层降级。
    """
    return f"{attendee_count} 位同事已就位，议程已加载"


def _llm_copy(meeting: Meeting, attendee_count: int) -> str | None:
    """用 LLM 生成一句会议页引导语。

    得到的数据：
        meeting（会议行，含 subject / timezone / 起止时间）；
        attendee_count（参会人数）。

    要做的操作：
        t1 未配置 LLM 凭据 → None（不打请求）；
        t2 把标题、人数、会议室本地时段喂给模型，要求输出 {"tagline": "..."}；
        t3 校验产出：长度 4~40 字、不含敏感词（防止模型把敏感信息写回来）；
        t4 任一校验不过 → None，由调用方降级到模板。

    返回：
        "议程已就绪，欢迎各位入座"（示例）；失败/未配置为 None。

    为什么：文案是唯一需要"语感"的字段，交给模型性价比最高；
            但敏感词必须二次校验——模型并不知道哪些词在公司内是禁语。
    """
    if not llm.available():
        return None

    system = "你是会议室门口电子屏的文案助手。只用中文，只输出 JSON，不要任何解释。"
    user = (
        f"会议标题：{meeting.subject}\n"
        f"参会人数：{attendee_count}\n"
        f"会议时段：{local_time_range(meeting.start_time_utc, meeting.end_time_utc, meeting.timezone)}\n"
        "请生成一句 12~24 字的会议页引导语：专业、简洁、有礼，"
        "不要出现人名、公司名、薪资、绩效、面试、并购等敏感信息，不要带标点结尾。\n"
        '输出格式：{"tagline": "这里是文案"}'
    )
    data = llm.chat_json(system, user, max_tokens=120, purpose="copy")
    tagline = (data or {}).get("tagline")
    if not isinstance(tagline, str):
        return None

    tagline = tagline.strip().strip('"').strip()
    if not 4 <= len(tagline) <= 40:
        return None
    if is_sensitive(tagline):
        return None
    return tagline


def build_meeting_content(meeting: Meeting) -> dict:
    """生成会议页要展示的全部内容。

    得到的数据：
        meeting（会议行，含 subject/attendees/timezone/起止时间）。

    要做的操作：
        t1 敏感判定：命中 → 标题「会议中」+ 安全文案，**跳过生成**，degraded=sensitive；
        t2 未命中 → 试 LLM：成功 degraded=llm，失败 degraded=template 并走模板文案；
        t3 组装品牌、参会人、本地时间、时区偏移。

    返回：
        {"title": "产品评审会", "tagline": "议程已就绪，欢迎各位入座",
         "attendees": ["张三", "李四"], "organizer": "zhangsan",
         "time_label": "10:00 – 11:00", "timezone": "Asia/Shanghai",
         "utc_offset": "+08:00", "is_sensitive": False, "degraded": "llm"}

    为什么：会议页（WebView/浏览器）只需要"已经算好的展示字段"，不该在设备端做业务判断；
            degraded 字段让后台一眼看出这场会到底走了哪条路径（llm / template / sensitive）。
    """
    attendees = list(meeting.attendees)
    organizer = meeting.organizer_email.split("@")[0]
    sensitive = is_sensitive(meeting.subject)

    if sensitive:
        # 命中敏感：标题与文案都用固定安全值，真实标题绝不外泄
        title = MASKED_TITLE
        tagline = MASKED_TAGLINE
        degraded = "sensitive"
    else:
        title = meeting.subject
        llm_tagline = _llm_copy(meeting, len(attendees))
        if llm_tagline:
            tagline = llm_tagline
            degraded = "llm"
        else:
            tagline = _template_copy(meeting, len(attendees))
            degraded = "template"

    return {
        "title": title,
        "tagline": tagline,
        "attendees": attendees,
        "organizer": organizer,
        "time_label": local_time_range(meeting.start_time_utc, meeting.end_time_utc, meeting.timezone),
        "timezone": meeting.timezone,
        "utc_offset": utc_offset_label(meeting.start_time_utc, meeting.timezone),
        "is_sensitive": sensitive,
        "degraded": degraded,
        "brand": BRAND,
    }

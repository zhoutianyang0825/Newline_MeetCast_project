"""全局配置唯一入口（改参数只来这里，别再散落在各模块）

分三组：
  【服务地址】PUBLIC_BASE          —— 设备页/素材 url 的域名前缀
  【调度参数】PREPARE/SWITCH/UPLOAD 提前量、TICK 间隔、fixture 首场会议偏移
  【存储与安全】UPLOAD_DIR、文件/配额上限、格式白名单、JWT 密钥

全部可用环境变量覆盖，默认值面向本机 demo。
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """把 server/.env 里的键值读进环境变量（不覆盖已存在的）。

    得到的数据：
        server/.env（若存在，格式为 KEY=VALUE，每行一个，# 开头为注释）。

    要做的操作：
        逐行解析 → os.environ.setdefault（已有环境变量优先，容器部署时不会被文件覆盖）。

    返回：
        无。

    为什么：LLM/Graph 凭据属于敏感信息，不进代码也不进 git；
             放 .env 后 local 开发只改一个文件，生产仍可用环境变量覆盖。
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ---------- 【服务地址】 ----------

# 设备页与素材 url 的前缀（换域名/端口只改这里）
PUBLIC_BASE = os.environ.get("MEETCAST_PUBLIC_BASE", "http://localhost:8000")

# ---------- 【调度参数】（PRD F2.4 / F3.2） ----------

# 会前 10 分钟预拉取、会前 1 分钟切屏
PREPARE_LEAD_MIN = 10
SWITCH_LEAD_MIN = 1

# 上传截止 = 会前 30 分钟（F2.4）
UPLOAD_LEAD_MIN = 30

# 调度节拍：demo 60 秒便于观察，生产按 PRD 走 300 秒
TICK_SEC = int(os.environ.get("MEETCAST_TICK_SEC", "60"))

# fixture 首场会议距离启动多少分钟：默认 8（落在预拉取窗口内），彩排可调 3
FIRST_MEETING_MIN = int(os.environ.get("MEETCAST_FIRST_MEETING_MIN", "8"))

# 会议时长（分钟）
MEETING_LEN_MIN = 60

# 离线判定：90 秒无心跳标 offline（≈3 次×30s 心跳，F1.2）
OFFLINE_TIMEOUT_SEC = 90
OFFLINE_SWEEP_INTERVAL_SEC = 15

# ---------- 【存储与安全】 ----------

# 上传落盘目录（pathlib，避免手拼字符串）
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

# 常规格式白名单：冷门格式明确拒绝（F4.1 → 2005）
ACCEPTED_FORMATS = {"png", "jpg", "jpeg", "mp4", "mp3"}

# 单文件上限 500MB（规范 §4.2 定稿）
MAX_FILE_MB = 500
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

# 分块读写单位：整包 read() 会把 500MB 塞进内存
CHUNK_BYTES = 1024 * 1024

# 素材库配额（2011 判定口径：条数 + 总容量）
MAX_MATERIALS = 500
MAX_TOTAL_MB = 102400

# JWT 签名密钥：生产从环境变量注入，dev 默认值仅供本机联调
JWT_SECRET = os.environ.get("MEETCAST_JWT_SECRET", "dev-secret-change-me")

# 日历源故障注入（开发期验证 3001/3002 用）：空 / "expired" / "rate_limited"
CALENDAR_FAULT = os.environ.get("MEETCAST_CALENDAR_FAULT", "")

# ---------- 【Graph 接入】（F2.1 / F2.3，开发期无实账户，默认走 Mock） ----------

# 1=用 fixture 假日历；0=真调 Microsoft Graph（需要下面三个凭据）
GRAPH_MOCK = os.environ.get("MEETCAST_GRAPH_MOCK", "1") == "1"
GRAPH_TENANT_ID = os.environ.get("MEETCAST_GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID = os.environ.get("MEETCAST_GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("MEETCAST_GRAPH_CLIENT_SECRET", "")

# 编排拉取窗口（驱动状态机）与链接生成窗口（发现新会议 → 发上传链接），PRD F2.4
SCHEDULE_WINDOW_HOURS = 12
LINK_WINDOW_DAYS = 7

# 1=邮件只打印/落库不真发（开发期无 Mail.Send 权限）；0=走 Graph sendMail
MAIL_MOCK = os.environ.get("MEETCAST_MAIL_MOCK", "1") == "1"

# ---------- 【数据持久化】（M1：内存库 → PostgreSQL，ADR D1） ----------
# 生产配 PG：postgresql+psycopg://user:pass@host:5432/meetcast
# 开发默认 SQLite 文件（零依赖即开即用；模型全部跨库可移植，评审决策 #1/#2）
DATABASE_URL = os.environ.get(
    "MEETCAST_DATABASE_URL",
    os.environ.get("DATABASE_URL", "sqlite:///data/meetcast.db"),
)

# ---------- 【LLM 接入】（F5.1 文案生成 / F3.5 智能选版式） ----------
# OpenAI 兼容协议：DeepSeek、阿里百炼、vLLM、Ollama 都能直接用。
# 不填 API Key → 自动回落模板文案 + 规则选版（绝不影响主链路）。
LLM_BASE_URL = os.environ.get(
    "MEETCAST_LLM_BASE_URL",
    os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
)
LLM_API_KEY = os.environ.get(
    "MEETCAST_LLM_API_KEY",
    os.environ.get("LLM_API_KEY", ""),
)
LLM_MODEL = os.environ.get(
    "MEETCAST_LLM_MODEL",
    os.environ.get("LLM_MODEL", "deepseek-chat"),
)
# 超时预算：PRD 要求"生成 ≤10 秒、失败 5 秒内降级"，这里取 6 秒留余量
LLM_TIMEOUT_SEC = float(os.environ.get("MEETCAST_LLM_TIMEOUT", "6"))

# ---------- 【标牌时段策略】（F3.4：早/中/晚三套标牌） ----------
# start_hour 含、end_hour 不含；按会议室本地时区判定，不按服务器时区
SIGNAGE_SLOTS = (
    {"name": "morning", "label": "上午标牌", "start_hour": 0, "end_hour": 12, "playlist": "brand_morning"},
    {"name": "afternoon", "label": "下午标牌", "start_hour": 12, "end_hour": 18, "playlist": "brand_afternoon"},
    {"name": "evening", "label": "夜间标牌", "start_hour": 18, "end_hour": 24, "playlist": "brand_evening"},
)

"""Pydantic 模型：设备端 3 接口的入参与出参（model 即文档，对齐 API 规范 §2）"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 陌生点 Literal["..."]：Python typing 的枚举约束。
#   是什么：限定值只能是列表里的那几个字符串；
#   起什么作用：device_state 只许这四个状态，status 只许 SUCCESS/FAILED；
#   为什么用：Pydantic 校验直接拒掉非法值 → 全局 handler 转 1001，不用手写 if。
DeviceState = Literal["IDLE", "MEETING_PREP", "MEETING", "FALLBACK"]


# ============ 2.1 POST /api/device/poll ============

class PollRequest(BaseModel):
    """poll 接口入参：设备身份 + 固件版本。

    字段：device_id（设备身份，开机画面展示的那个，如 "SH-A3-01-01"）；agent_version（APK 版本，如 "1.0.0"）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"], description="设备身份，开机画面展示的那个")
    agent_version: str = Field("0.0.0", examples=["1.0.0"], description="设备端 Agent/APK 版本号")


class PollCommandOut(BaseModel):
    """poll 接口 data 的形态：有指令 = 一条待执行指令；无指令 = 只有 command_id=None。

    字段：command_id（幂等键）；type（指令类型）；payload（指令参数）；initiated_by（触发方，审计必埋）；checksum（完整性校验）。
    """

    command_id: str | None = Field(None, examples=["cmd_9f3a1b"])
    type: str | None = Field(None, examples=["PREPARE_MEETING"])
    payload: dict[str, Any] | None = None
    initiated_by: str | None = Field(None, examples=["system"], description="谁触发的（审计必埋，F8.3）")
    checksum: str | None = Field(None, description="指令完整性校验 sha256")


# ============ 2.2 POST /api/device/ack ============

class AckRequest(BaseModel):
    """ack 接口入参：设备执行完指令后回报的结果。

    字段：command_id（要回执的指令）；status（只许 SUCCESS/FAILED，其他值 → 1001）；device_state（执行后的设备状态，可选）。
    """

    command_id: str = Field(..., examples=["cmd_9f3a1b"])
    status: Literal["SUCCESS", "FAILED"] = Field(..., description="只允许这两个值，其他值 → 1001")
    device_state: DeviceState | None = Field(None, examples=["MEETING"], description="执行后的设备状态，可选")


# ============ 2.3 POST /api/device/heartbeat ============

class HeartbeatRequest(BaseModel):
    """heartbeat 接口入参：30s 一次的状态采集。

    字段：device_id（设备身份）；device_state（设备状态枚举）；playing（当前播放内容标识）；storage_used_mb（素材占用 MB）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    device_state: DeviceState = Field("IDLE", examples=["IDLE"])
    playing: str | None = Field("signage_default", description="当前播放内容标识")
    storage_used_mb: float | None = Field(0, description="素材占用（MB），15 天清理依据")


class HeartbeatOut(BaseModel):
    """heartbeat 接口 data：服务器 UTC 时间，设备据此校时。

    字段：server_time_utc（如 "2026-10-27T04:26:12Z"）。
    """

    server_time_utc: str = Field(..., examples=["2026-10-27T04:26:12Z"])


# ============ 2.4 GET /api/device/profile ============

class DeviceProfileOut(BaseModel):
    """设备档案：设备开机后第一件事——搞清"我是谁、我绑在哪"。

    字段：device_id（身份，开机画面大字展示）；device_name（展示名）；bound（是否已绑定会议室）；
    room_id/room_name（绑定的会议室，未绑定为 null）；timezone（渲染与本地定时用）；
    server_time_utc（校时）；agent_version（设备上报的版本）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    device_name: str = Field("", examples=["上海 A3 栋 01 会议室屏"])
    bound: bool = Field(..., examples=[True], description="room_id 是否有值，设备据此决定显示标牌还是未绑定页")
    room_id: str | None = Field(None, examples=["room-a3-01"])
    room_name: str | None = Field(None, examples=["上海 A3-01"])
    timezone: str = Field("Asia/Shanghai", examples=["Asia/Shanghai"], description="会议室 IANA 时区")
    server_time_utc: str = Field(..., examples=["2026-10-27T04:26:12Z"])
    agent_version: str = Field("0.0.0", examples=["1.0.0"])


# ============ 2.5 GET /api/device/schedule ============

class ScheduleItemOut(BaseModel):
    """日程条目：会议室当日一场会议的设备视图。

    字段：meeting_id（追溯用）；subject（已脱敏的标题）；start/end_time_utc（UTC）；
    time_label（会议室本地 "10:00 – 11:00"）；is_current（进行中）；is_next（下一场）；
    content_url（该会议的渲染页地址，设备可直接预拉取）。
    """

    meeting_id: str = Field(..., examples=["meeting_a3_01_0"])
    subject: str = Field(..., examples=["产品评审会"])
    start_time_utc: str = Field(..., examples=["2026-10-27T02:08:00Z"])
    end_time_utc: str = Field(..., examples=["2026-10-27T03:08:00Z"])
    time_label: str = Field(..., examples=["10:08 – 11:08"])
    status: str = Field("scheduled", examples=["scheduled"])
    is_current: bool = Field(False, description="当前时刻是否已开始未结束")
    is_next: bool = Field(False, description="是否是下一场（标牌页\"即将开始\"用）")
    content_url: str = Field(..., examples=["http://localhost:8000/ui/display/meeting.html?..."])
    is_sensitive: bool = Field(False, description="标题是否命中敏感词（已脱敏为\"会议中\"）")


class DeviceScheduleOut(BaseModel):
    """日程列表：设备绑定会议室的滚动窗口日程（默认未来 24h，含进行中）。

    字段：bound（未绑定时 items 为空，设备显示未绑定页）；room_id/room_name/timezone；
    window_hours（窗口长度）；server_time_utc（校时）；items（按开始时间升序）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    bound: bool = Field(..., examples=[True])
    room_id: str | None = None
    room_name: str | None = None
    timezone: str = Field("Asia/Shanghai")
    window_hours: int = Field(24, examples=[24])
    server_time_utc: str = Field(..., examples=["2026-10-27T04:26:12Z"])
    items: list[ScheduleItemOut] = Field(default_factory=list)


# ============ 2.6 GET /api/device/materials ============

class MaterialEntryOut(BaseModel):
    """设备应缓存的单个素材。

    字段：material_id/name/format/size_mb（文件信息）；url（下载地址）；checksum（完整性校验，大文件为部分哈希）；
    scope（public/meeting）；meeting_id（专属素材所属会议）；expire_at（到期时刻，设备据此清理）；
    reason（为什么该缓存：public 或 meeting:<id>，便于现场排查）。
    """

    material_id: str = Field(..., examples=["mat_001"])
    name: str = Field(..., examples=["brand-default.png"])
    format: str = Field(..., examples=["png"])
    size_mb: float = Field(2.4, examples=[2.4])
    url: str = Field(..., examples=["http://localhost:8000/media/mat_001.png"])
    checksum: str | None = Field(None, description="sha256:... 或大文件 sha256-partial:...")
    scope: str = Field("public", examples=["public"])
    meeting_id: str | None = None
    expire_at: str | None = Field(None, description="到期时刻，设备本地据此删缓存")
    reason: str = Field(..., examples=["public"], description="public / meeting:<meeting_id>")


class DeviceMaterialsOut(BaseModel):
    """素材清单：该设备当前应缓存的全集（公共 + 本会议室各会议专属）。

    字段：bound；room_id；total_mb/count（配额与进度展示）；server_time_utc；items。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    bound: bool = Field(..., examples=[True])
    room_id: str | None = None
    total_mb: float = Field(0, examples=[2.4])
    count: int = Field(0, examples=[1])
    server_time_utc: str = Field(..., examples=["2026-10-27T04:26:12Z"])
    items: list[MaterialEntryOut] = Field(default_factory=list)


# ============ 统一返回壳 { code, message, data } ============

class ApiResponse(BaseModel):
    """所有接口的统一返回壳。

    字段：code（0 成功，非 0 报错）；message（人看的提示语）；data（业务数据，出错时 null）。
    """

    code: int = 0
    message: str = "ok"
    data: Any = None


# ============ 3.1 GET /api/admin/devices ============

class DeviceListItem(BaseModel):
    """设备列表单条（后台设备管理页一行的数据）。

    字段：device_id/device_name（身份）；room_id/room_name（绑定关系）；status/device_state/playing/agent_version/last_heartbeat/storage_used_mb（状态采集）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    device_name: str = Field("", examples=["device_sh_003"])
    room_id: str | None = Field(None, examples=["room-a3-01"])
    room_name: str | None = Field(None, examples=["Room-A3-01 · 上海总部 3F"])
    status: Literal["online", "offline"] = "offline"
    device_state: DeviceState = "IDLE"
    playing: str = Field("", description="当前播放内容标识")
    agent_version: str = ""
    last_heartbeat: str | None = None
    storage_used_mb: float = 0


# ============ 3.2 / 3.3 绑定 / 解绑 ============

class BindRequest(BaseModel):
    """bind 接口入参：把设备绑到会议室（场景 B 终点）。

    字段：device_id（设备身份）；room_id（目标会议室）；force（true=强制覆盖设备/会议室的已有绑定）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    room_id: str = Field(..., examples=["room-a3-01"])
    force: bool = False


class BindOut(BaseModel):
    """bind 接口 data：绑定结果。

    字段：device_id/room_id（绑定关系）；bound_at（绑定时刻）；effective_in_sec（调度生效倒计时，固定 300）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    room_id: str = Field(..., examples=["room-a3-01"])
    bound_at: str = Field(..., examples=["2026-10-27T04:30:00Z"])
    effective_in_sec: int = Field(300, description="换绑后 5 分钟内调度生效（F1 验收）")


class UnbindRequest(BaseModel):
    """unbind 接口入参。

    字段：device_id（要解绑的设备身份）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])


# ============ 4.1 / 4.2 / 4.3 素材 ============

class MaterialItem(BaseModel):
    """素材列表单条（素材库一行）。

    字段：material_id/name/format/size_mb/url（文件本体）；scope（public/meeting）；meeting_id（专属素材所属会议）；tags（分类标签）；uploaded_by（谁传的）；expire_at（专属素材会后过期）；created_at（上传时间）。
    """

    material_id: str = Field(..., examples=["mat_001"])
    name: str = Field(..., examples=["Q3-review-cover.png"])
    format: str = Field(..., examples=["png"])
    size_mb: float = 2.4
    url: str = Field(..., examples=["http://localhost:8000/media/mat_001.png"])
    scope: Literal["public", "meeting"] = "public"
    meeting_id: str | None = None
    category: str = Field("other", examples=["brand"], description="一级业务分类：brand/culture/meeting/other")
    tags: list[str] = Field(default_factory=list, examples=[["brand", "cover"]])
    uploaded_by: str = Field("", examples=["admin:admin_001"])
    expire_at: str | None = None
    created_at: str = ""


class MaterialUploadOut(BaseModel):
    """素材上传成功返回。

    字段：material_id（新素材 id）；url（可访问地址）。
    """

    material_id: str = Field(..., examples=["mat_032"])
    url: str = Field(..., examples=["http://localhost:8000/media/mat_032.png"])


# ============ 5.1 / 5.2 免登录上传 ============

class UploadedFileItem(BaseModel):
    """已上传文件条目（上传页列表展示）。

    字段：name（文件名）；size_mb（大小）；status（处理状态，固定 ready）。
    """

    name: str = Field(..., examples=["Q3-review-cover.png"])
    size_mb: float = 2.4
    status: str = "ready"


class UploadInfoOut(BaseModel):
    """免登录上传页 data：会议信息 + 上传规则 + 已传文件。

    字段：meeting_id/subject/room_name（会议与地点）；start_time_utc/end_time_utc/timezone（时间与渲染时区）；upload_deadline_utc（截止时刻）；max_size_mb/accepted_formats（上传约束）；uploaded（已传列表）。
    """

    meeting_id: str = Field(..., examples=["meeting_123"])
    subject: str = Field(..., examples=["产品评审会"])
    room_name: str = Field(..., examples=["Room-A3-01 · 上海总部 3F"])
    start_time_utc: str = Field(..., examples=["2026-10-27T02:00:00Z"])
    end_time_utc: str = Field(..., examples=["2026-10-27T03:00:00Z"])
    timezone: str = Field(..., examples=["Asia/Shanghai"])
    upload_deadline_utc: str = Field(..., examples=["2026-10-27T01:30:00Z"])
    max_size_mb: int = 500
    accepted_formats: list[str] = Field(default_factory=list)
    uploaded: list[UploadedFileItem] = Field(default_factory=list)


class UploadResultOut(BaseModel):
    """免登录上传成功返回。

    字段：material_id（新素材 id）；name（原文件名）；status（固定 ready）。
    """

    material_id: str = Field(..., examples=["mat_001"])
    name: str = Field(..., examples=["Q3-review-cover.png"])
    status: str = "ready"


# ============ 6.1 / 6.2 / 6.3 日历源 ============

class PullPolicy(BaseModel):
    """拉取策略（分层拉取，F2.4）。

    字段：schedule（编排拉取：开关/间隔/窗口小时）；link_gen（链接生成拉取：开关/间隔/窗口天）；dst_enabled（夏令时换算开关）。
    """

    schedule: dict = Field(default_factory=lambda: {"enabled": True, "interval_min": 5, "window_hours": 12})
    link_gen: dict = Field(default_factory=lambda: {"enabled": True, "interval_min": 30, "window_days": 7})
    dst_enabled: bool = True


class CalendarConfigIn(BaseModel):
    """日历配置入参（PUT 用；connection_status / credential_expire_at 只读，不在入参里）。

    字段：provider/tenant/service_account（接入身份）；scopes（服务端固定，传了也不生效）；pull_policy（拉取策略）；alert_email（告警收件人）。
    """

    provider: str = Field("m365", examples=["m365"])
    tenant: str = Field("honghe.onmicrosoft.com")
    service_account: str = Field("svc-meetcast@honghe.com")
    scopes: list[str] | None = Field(None, description="服务端固定，传了也不生效")
    pull_policy: PullPolicy = Field(default_factory=PullPolicy)
    alert_email: str = Field("it-admin@honghe.com")


class CalendarTestOut(BaseModel):
    """日历连接测试结果（F2.7）。

    字段：auth_ok（鉴权是否通）；rooms_synced（同步到几间会议室）；api_latency_ms（调用耗时）；checked_at（检测时刻）。
    """

    auth_ok: bool = True
    rooms_synced: int = 4
    api_latency_ms: int = 420
    checked_at: str = ""


# ============ 7.1 / 7.2 运维 ============

class CommandItem(BaseModel):
    """指令审计单条（F7.1）。

    字段：command_id（幂等键）；device_id（目标设备）；type（指令类型）；status（PENDING/SENT/ACKED/FAILED/TIMEOUT）；initiated_by（谁触发，F8.3）；created_at/acked_at（时间）；retry_count（重试次数）。
    """

    command_id: str = Field(..., examples=["cmd_9f3a1b"])
    device_id: str = Field(..., examples=["SH-A3-01-01"])
    type: str = Field(..., examples=["PREPARE_MEETING"])
    status: str = Field(..., examples=["ACKED"])
    initiated_by: str = Field(..., examples=["system"])
    created_at: str = ""
    acked_at: str | None = None
    retry_count: int = 0


class SwitchRequest(BaseModel):
    """手动干预切换入参（F7.5，唯一允许人工触发 SWITCH_CONTENT 的入口）。

    字段：device_id（目标设备）；content_url（要显示的内容地址）；until（保持到什么时候，UTC）。
    """

    device_id: str = Field(..., examples=["SH-A3-01-01"])
    content_url: str = Field(..., examples=["https://meetcast.app/c/emergency"])
    until: str = Field(..., examples=["2026-10-27T05:00:00Z"])


class SwitchOut(BaseModel):
    """手动切换返回。

    字段：command_id（新指令 id，前端可拿去查审计）。
    """

    command_id: str = Field(..., examples=["cmd_a1b2c3"])


# ============ 登录（补充接口，规范 §十） ============

class LoginRequest(BaseModel):
    """登录入参。

    字段：email（登录邮箱）；password（明文口令，只在传输层出现）。
    """

    email: str = Field(..., examples=["admin@honghe.com"])
    password: str = Field(..., examples=["admin123"])


class LoginOut(BaseModel):
    """登录返回。

    字段：token（JWT）；user_id（审计用）；name（展示名）；role（admin/user）；expires_in（有效期秒数）。
    """

    token: str = Field(..., examples=["eyJhbGciOiJIUzI1NiJ9..."])
    user_id: str = Field(..., examples=["admin_001"])
    name: str = Field(..., examples=["管理员"])
    role: str = Field(..., examples=["admin"])
    expires_in: int = 28800

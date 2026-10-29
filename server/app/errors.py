"""统一错误码与业务异常（与 Newline_MeetCast_API_Spec.md §1.2 对齐）"""

from __future__ import annotations


# ---- 错误码常量（设备端 3 接口 + 管理端设备 3 接口用到的 + 兜底） ----
CODE_OK = 0                 # 成功
CODE_PARAM_INVALID = 1001   # 参数校验失败（缺字段/类型错/枚举值非法）
CODE_UNAUTHORIZED = 1002    # 未认证（X-Device-Key 缺失或错误 / JWT 缺失或过期）
CODE_NO_PERMISSION = 1003   # 无权限（非管理员调管理端接口）
CODE_DEVICE_NOT_FOUND = 2001   # 设备不存在（device_id 未注册）
CODE_COMMAND_NOT_FOUND = 2004  # command_id 不存在（规范 §2.2 指定用 2004）
CODE_MATERIAL_NOT_FOUND = 2004  # 素材不存在（规范 §4.3 与 command 共用 2004，靠 message 区分）
CODE_DEVICE_ALREADY_BOUND = 2002  # 设备已绑定（换绑需 force=true）
CODE_ROOM_NOT_FOUND = 2003  # 会议室不存在（room_id 非法）
CODE_ROOM_BOUND_OTHER = 2008  # 会议室已绑定其他设备（换绑需 force=true）
CODE_TOKEN_INVALID = 1004   # 免登录 token 无效/过期/超额（F4.7）
CODE_FORMAT_UNSUPPORTED = 2005  # 格式不支持（冷门格式明确拒绝，F4.1）
CODE_UPLOAD_CLOSED = 2006   # 上传已截止（会前 30 分钟，F2.4）
CODE_FILE_TOO_LARGE = 2007  # 单文件 > 500MB
CODE_DEVICE_OFFLINE = 2009  # 设备离线（命令入队 PENDING，上线后经 poll 下发）
CODE_MEETING_UNAVAILABLE = 2010  # 会议不存在或已取消
CODE_QUOTA_EXCEEDED = 2011  # 素材配额超限
CODE_CALENDAR_CRED_INVALID = 3001  # 日历源凭证失效
CODE_CALENDAR_RATE_LIMITED = 3002  # 日历 API 超限（429）
CODE_INTERNAL = 5000        # 服务内部错误兜底

# 错误码 → 默认 message（人看的提示语）
MESSAGES: dict[int, str] = {
    CODE_OK: "ok",
    CODE_PARAM_INVALID: "参数校验失败",
    CODE_UNAUTHORIZED: "未认证",
    CODE_NO_PERMISSION: "无权限",
    CODE_TOKEN_INVALID: "token 无效或已过期",
    CODE_DEVICE_NOT_FOUND: "设备不存在",
    CODE_COMMAND_NOT_FOUND: "command_id 不存在",
    CODE_DEVICE_ALREADY_BOUND: "设备已绑定",
    CODE_ROOM_NOT_FOUND: "会议室不存在",
    CODE_FORMAT_UNSUPPORTED: "格式不支持",
    CODE_UPLOAD_CLOSED: "上传已截止",
    CODE_FILE_TOO_LARGE: "文件超限（单文件上限 500MB）",
    CODE_ROOM_BOUND_OTHER: "会议室已绑定其他设备",
    CODE_DEVICE_OFFLINE: "设备离线，指令已入队",
    CODE_MEETING_UNAVAILABLE: "会议不存在或已取消",
    CODE_QUOTA_EXCEEDED: "素材配额超限",
    CODE_CALENDAR_CRED_INVALID: "日历源凭证失效",
    CODE_CALENDAR_RATE_LIMITED: "日历 API 超限",
    CODE_INTERNAL: "服务内部错误",
}


class ApiError(Exception):
    """业务异常：路由里 raise 出来，由全局 handler 转成统一错误壳。

    字段：code（错误码，如 2001）；message（人看的提示语，如 "设备不存在"）。
    """

    def __init__(self, code: int, message: str | None = None) -> None:
        # message 不传就用错误码默认文案
        self.code = code
        self.message = message or MESSAGES.get(code, "unknown error")
        super().__init__(self.message)

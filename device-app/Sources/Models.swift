import Foundation

/// 服务端统一返回壳：{ code, message, data }。
///
/// 得到的数据：
///     服务端 JSON（snake_case，由 decoder 统一转 camelCase）。
///
/// 要做的操作：
///     泛型解码 data；code != 0 时由 APIClient 抛业务错误。
///
/// 返回：
///     APIEnvelope<T>，data 可能为 null（如 ack 返回 data=null）。
///
/// 为什么：全项目只有一个返回壳，泛型化后每个接口不用各写一遍解壳逻辑。
struct APIEnvelope<T: Decodable>: Decodable {
    let code: Int
    let message: String
    let data: T?
}

/// 空返回体（ack 这类 data=null 的接口用）。
struct EmptyData: Decodable {}

/// 设备档案（GET /api/device/profile）。
///
/// 字段：device_id/device_name（身份）；bound/room_id/room_name（绑定状态）；
/// timezone（本地定时与展示口径）；server_time_utc（校时）；agent_version。
struct DeviceProfile: Decodable {
    let deviceId: String
    let deviceName: String?
    let bound: Bool
    let roomId: String?
    let roomName: String?
    let timezone: String?
    let serverTimeUtc: String?
    let agentVersion: String?
}

/// 日程条目（GET /api/device/schedule 的 items[]）。
///
/// 字段：meeting_id/subject（标题已脱敏）；start/end_time_utc；time_label（本地时间段）；
/// status；is_current/is_next（进行中/下一场）；content_url（可直接预拉取渲染页）。
struct ScheduleItem: Decodable, Identifiable {
    let meetingId: String
    let subject: String
    let startTimeUtc: String
    let endTimeUtc: String
    let timeLabel: String
    let status: String
    let isCurrent: Bool
    let isNext: Bool
    let contentUrl: String
    let isSensitive: Bool

    var id: String { meetingId }
}

/// 日程列表返回体（GET /api/device/schedule）。
struct DeviceSchedule: Decodable {
    let deviceId: String
    let bound: Bool
    let roomId: String?
    let roomName: String?
    let timezone: String?
    let windowHours: Int
    let serverTimeUtc: String?
    let items: [ScheduleItem]
}

/// 应缓存素材（GET /api/device/materials 的 items[]）。
///
/// 字段：material_id/name/format/size_mb（文件信息）；url/checksum（下载与校验）；
/// expire_at（到期清理依据）；reason（public 或 meeting:<id>，排查用）。
struct MaterialEntry: Decodable, Identifiable {
    let materialId: String
    let name: String
    let format: String
    let sizeMb: Double
    let url: String
    let checksum: String?
    let scope: String
    let meetingId: String?
    let expireAt: String?
    let reason: String

    var id: String { materialId }
}

/// 素材清单返回体（GET /api/device/materials）。
struct DeviceMaterials: Decodable {
    let deviceId: String
    let bound: Bool
    let roomId: String?
    let totalMb: Double
    let count: Int
    let serverTimeUtc: String?
    let items: [MaterialEntry]
}

/// 指令 payload（不同指令类型填不同字段，全部可选）。
///
/// 字段：content_url（渲染页地址）；meeting_id（追溯）；prepare_at/switch_at（双时刻）；
/// until（结束时刻）；timezone（本地定时口径）；slot（标牌时段）；
/// material_ids（CLEAN_MATERIAL 要清理的素材）。
struct CommandPayload: Decodable {
    let contentUrl: String?
    let meetingId: String?
    let prepareAt: String?
    let switchAt: String?
    let until: String?
    let timezone: String?
    let slot: String?
    let materialIds: [String]?
}

/// 一条待执行指令（GET/POST /api/device/poll 的 data）。
///
/// 字段：command_id（幂等键，回执必带）；type（指令类型）；payload（参数）；
/// initiated_by（谁触发，日志用）；checksum（完整性校验）。
struct PollCommand: Decodable {
    let commandId: String?
    let type: String?
    let payload: CommandPayload?
    let initiatedBy: String?
    let checksum: String?

    /// 超时无指令时服务端返回 command_id=null，用这个判断"这次没活干"
    var isEmpty: Bool { commandId == nil }
}

/// 心跳返回体（POST /api/device/heartbeat 的 data）。
struct HeartbeatResult: Decodable {
    let serverTimeUtc: String
}

/// 业务错误：服务端 code 非 0 时抛出。
///
/// 字段：code（业务码，如 1002/2001）；message（服务端提示语）。
struct APIError: Error, LocalizedError {
    let code: Int
    let message: String

    var errorDescription: String? { "code=\(code) \(message)" }

    /// 密钥失效：设备需要重新绑定（1002 未认证 / 2001 设备不存在）
    var requiresRebind: Bool { code == 1002 || code == 2001 }
}

import Foundation

/// 设备端 HTTP 客户端：所有与服务端的通信都从这里走。
///
/// 得到的数据：
///     构造时读 Settings.baseURL；运行时每次调用带 X-Device-Key。
///
/// 要做的操作：
///     统一解包 { code, message, data }；code != 0 抛 APIError；
///     poll 用独立的"长超时"会话（服务端 hold 25s）。
///
/// 返回：
///     单例 APIClient，方法均为 async。
///
/// 为什么：长轮询和普通请求的超时语义完全不同——共用一个 session 会让
///         普通请求也跟着等 40s，或让长轮询 30s 就断。两套 session 是必须的。
final class APIClient {
    static let shared = APIClient()

    /// 普通请求：短超时，失败快速重试
    private let normalSession: URLSession
    /// 长轮询专用：超时必须大于服务端 hold（25s）
    private let pollSession: URLSession

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private init() {
        let normalConfig = URLSessionConfiguration.ephemeral
        normalConfig.timeoutIntervalForRequest = 15
        normalConfig.timeoutIntervalForResource = 120
        normalConfig.waitsForConnectivity = false
        normalSession = URLSession(configuration: normalConfig)

        let pollConfig = URLSessionConfiguration.ephemeral
        pollConfig.timeoutIntervalForRequest = Settings.pollTimeout
        pollConfig.timeoutIntervalForResource = Settings.pollTimeout + 10
        pollSession = URLSession(configuration: pollConfig)
    }

    // MARK: - 底层请求

    /// 发一个请求并解包统一返回壳。
    ///
    /// 得到的数据：
    ///     path（如 "/api/device/profile"）；method（GET/POST）；
    ///     key（X-Device-Key）；body（POST 的 JSON 体，GET 传 nil）；
    ///     usePollSession（是否用长超时会话）。
    ///
    /// 要做的操作：
    ///     拼 URL → 设头 → 发请求 → 校验 HTTP 200 → 解 APIEnvelope → code!=0 抛 APIError。
    ///
    /// 返回：
    ///     解好的 data（如 DeviceProfile）；data 为 null 的接口返回 EmptyData。
    ///
    /// 为什么：把所有"网络异常 → 业务码异常"的分支收口，上层只处理 APIError 一种错误。
    private func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        key: String,
        query: [URLQueryItem] = [],
        body: [String: Any]? = nil,
        usePollSession: Bool = false
    ) async throws -> T {
        var components = URLComponents(url: Settings.baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)
        if !query.isEmpty { components?.queryItems = query }
        guard let url = components?.url else {
            throw APIError(code: -1, message: "URL 拼接失败：\(path)")
        }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue(key, forHTTPHeaderField: "X-Device-Key")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let session = usePollSession ? pollSession : normalSession
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw APIError(code: code, message: "HTTP \(code)")
        }

        let envelope: APIEnvelope<T>
        do {
            envelope = try decoder.decode(APIEnvelope<T>.self, from: data)
        } catch {
            throw APIError(code: -1, message: "响应解析失败：\(error.localizedDescription)")
        }
        guard envelope.code == 0 else {
            throw APIError(code: envelope.code, message: envelope.message)
        }
        guard let payload = envelope.data else {
            if let empty = EmptyData() as? T { return empty }
            throw APIError(code: -1, message: "data 为空")
        }
        return payload
    }

    // MARK: - 业务接口

    /// 校验密钥并取设备档案（设备"注册/激活"那一步）。
    ///
    /// 得到的数据：
    ///     key（用户输入的设备密钥，如 "dev-key-sh-a3-01-01"）。
    ///
    /// 要做的操作：
    ///     GET /api/device/profile。
    ///
    /// 返回：
    ///     DeviceProfile（bound/room 信息），密钥错抛 1002。
    ///
    /// 为什么：绑定页只有"点确认"一次机会，必须先用服务端确认密钥有效，
    ///         再落盘——否则会把错密钥永久写进配置，每次启动都失败。
    func profile(key: String) async throws -> DeviceProfile {
        try await request("/api/device/profile", key: key)
    }

    /// 拉本会议室滚动窗口日程。
    ///
    /// 得到的数据：
    ///     key；hours（往后看多少小时，默认 24）。
    ///
    /// 要做的操作：
    ///     GET /api/device/schedule?hours=...
    ///
    /// 返回：
    ///     DeviceSchedule（未绑定时 items 为空）。
    ///
    /// 为什么：标牌页"下一场"、开机预拉取目标都来自这里，不依赖指令也能显示日程。
    func schedule(key: String, hours: Int = 24) async throws -> DeviceSchedule {
        try await request("/api/device/schedule", key: key, query: [URLQueryItem(name: "hours", value: "\(hours)")])
    }

    /// 拉应缓存素材清单。
    ///
    /// 得到的数据：
    ///     key。
    ///
    /// 要做的操作：
    ///     GET /api/device/materials。
    ///
    /// 返回：
    ///     DeviceMaterials（含 checksum / expire_at）。
    ///
    /// 为什么：预拉取与 LRU 清理都必须以服务端清单为准，设备不自造规则。
    func materials(key: String) async throws -> DeviceMaterials {
        try await request("/api/device/materials", key: key)
    }

    /// 上报心跳。
    ///
    /// 得到的数据：
    ///     key；deviceId；deviceState（IDLE/MEETING_PREP/MEETING/FALLBACK）；
    ///     playing（当前播放标识）；storageMB（缓存占用）。
    ///
    /// 要做的操作：
    ///     POST /api/device/heartbeat。
    ///
    /// 返回：
    ///     HeartbeatResult（含 server_time_utc，用于校时）。
    ///
    /// 为什么：心跳同时承担"在线判定"和"校时"两件事——switch_at 定时切屏
    ///         完全依赖设备时钟准，30s 一次校准成本最低。
    func heartbeat(key: String, deviceId: String, deviceState: String, playing: String, storageMB: Double) async throws -> HeartbeatResult {
        try await request(
            "/api/device/heartbeat",
            method: "POST",
            key: key,
            body: [
                "device_id": deviceId,
                "device_state": deviceState,
                "playing": playing,
                "storage_used_mb": storageMB,
            ]
        )
    }

    /// 长轮询取指令。
    ///
    /// 得到的数据：
    ///     key；deviceId（服务端校验密钥与身份是否同一台）。
    ///
    /// 要做的操作：
    ///     POST /api/device/poll（服务端 hold 至有指令或 25s）。
    ///
    /// 返回：
    ///     PollCommand；超时无指令时 commandId 为 nil（用 isEmpty 判断）。
    ///
    /// 为什么：设备不开放端口，靠长轮询拿指令是 PRD §4.4 的核心，
    ///         超时即重连，实现"指令入队到设备取走 ≤5 秒"。
    func poll(key: String, deviceId: String) async throws -> PollCommand {
        try await request(
            "/api/device/poll",
            method: "POST",
            key: key,
            body: ["device_id": deviceId, "agent_version": Settings.agentVersion],
            usePollSession: true
        )
    }

    /// 指令回执。
    ///
    /// 得到的数据：
    ///     key；commandId；status（SUCCESS/FAILED）；deviceState（执行后状态）。
    ///
    /// 要做的操作：
    ///     POST /api/device/ack。
    ///
    /// 返回：
    ///     无（服务端 data=null）。
    ///
    /// 为什么：每条指令必须有终态，否则后台审计里永远停在 SENT，
    ///         重试机制也会误判"设备没执行"。
    func ack(key: String, commandId: String, status: String, deviceState: String) async throws {
        let _: EmptyData = try await request(
            "/api/device/ack",
            method: "POST",
            key: key,
            body: ["command_id": commandId, "status": status, "device_state": deviceState]
        )
    }

    /// 下载素材到本地文件。
    ///
    /// 得到的数据：
    ///     remote（服务端 url，如 http://localhost:8000/media/mat_001.png）；
    ///     target（本地目标路径）。
    ///
    /// 要做的操作：
    ///     用 download(for:) 走系统临时文件 → 移到目标路径（避免大文件进内存）。
    ///
    /// 返回：
    ///     落地字节数。
    ///
    /// 为什么：500MB 视频用 data(for:) 会整包进内存，download 任务直接落盘，
    ///         这是设备端"边下边存"的唯一稳妥做法。
    @discardableResult
    func download(remote: URL, to target: URL) async throws -> Int64 {
        let (tempURL, response) = try await normalSession.download(from: remote)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw APIError(code: -1, message: "下载失败 HTTP \((response as? HTTPURLResponse)?.statusCode ?? -1)")
        }
        try? FileManager.default.removeItem(at: target)
        try FileManager.default.moveItem(at: tempURL, to: target)
        let attrs = try? FileManager.default.attributesOfItem(atPath: target.path)
        let size = (attrs?[.size] as? NSNumber)?.int64Value ?? 0
        return size
    }
}

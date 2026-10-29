import Foundation

/// 设备凭据：设备端"注册"后的本地身份，重启后靠它继续工作。
///
/// 得到的数据：
///     无（结构体本身即持久化格式）。
///
/// 要做的操作：
///     保存 device_id / device_key / 与服务器的时钟偏差。
///
/// 返回：
///     Codable 值类型，由 ConfigStore 落盘到 device.json。
///
/// 为什么：设备重启后不能要求人工重新输入密钥——凭据必须落盘；
///         时钟偏差也要存，否则重启后 switch_at 定时又会用回不准的本机时间。
struct DeviceConfig: Codable {
    var deviceId: String
    var deviceKey: String
    /// 服务器时间 - 本机时间（秒）。正数表示本机慢了。
    var clockOffset: TimeInterval = 0

    /// 校准后的"现在"：本地时钟 + 偏差，用于 switch_at 本地定时
    var serverNow: Date {
        Date().addingTimeInterval(clockOffset)
    }
}

/// 凭据读写（单例，进程内共享）。
///
/// 得到的数据：
///     无（读取时从 Settings.configFile 加载）。
///
/// 要做的操作：
///     load() 读 JSON；save() 覆盖写；clear() 删除（解绑重置用）。
///
/// 返回：
///     单例 ConfigStore，config 为 nil 表示未绑定/未激活。
///
/// 为什么：设备端所有模块都要判断"有没有凭据"，收口成一个入口，
///         避免各处自己读文件导致状态不一致。
final class ConfigStore {
    static let shared = ConfigStore()

    private(set) var config: DeviceConfig?

    private init() {
        config = Self.read()
    }

    /// 从磁盘读凭据。
    ///
    /// 得到的数据：
    ///     无入参。
    ///
    /// 要做的操作：
    ///     读 device.json → JSONDecoder 解码；文件不存在或损坏 → nil。
    ///
    /// 返回：
    ///     DeviceConfig 或 nil（nil = 首次启动，需要绑定）。
    ///
    /// 为什么：文件损坏要当作"未绑定"处理，让用户重新录入，而不是崩在启动阶段。
    static func read() -> DeviceConfig? {
        guard let data = try? Data(contentsOf: Settings.configFile) else { return nil }
        return try? JSONDecoder().decode(DeviceConfig.self, from: data)
    }

    /// 写入凭据并更新内存副本。
    ///
    /// 得到的数据：
    ///     config（新的设备身份，含密钥）。
    ///
    /// 要做的操作：
    ///     JSONEncoder 编码 → 原子写 device.json → 更新 self.config。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：原子写（.atomic）保证不会出现"写一半断电导致凭据损坏"的半残文件。
    func save(_ config: DeviceConfig) {
        self.config = config
        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        guard let data = try? encoder.encode(config) else { return }
        try? data.write(to: Settings.configFile, options: .atomic)
    }

    /// 只更新校时偏差，不重写其余字段。
    ///
    /// 得到的数据：
    ///     offset（服务器时间 - 本机时间，秒）。
    ///
    /// 要做的操作：
    ///     有凭据则改 clockOffset 并落盘；没有凭据则忽略。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：心跳每 30s 就带来一次校准机会，落盘让设备重启后立刻有时间基准。
    func updateClockOffset(_ offset: TimeInterval) {
        guard var current = config else { return }
        current.clockOffset = offset
        save(current)
    }

    /// 清除凭据（设备被解绑且用户选择"重置设备"时用）。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     置空内存副本 + 删除 device.json。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：解绑后残留凭据会让设备反复用错身份请求，必须能彻底清掉。
    func clear() {
        config = nil
        try? FileManager.default.removeItem(at: Settings.configFile)
    }
}

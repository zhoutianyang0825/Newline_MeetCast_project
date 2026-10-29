import Foundation

/// 全局配置：所有"可变参数"只在这里出现一次。
///
/// 得到的数据：
///     环境变量 MEETCAST_BASE_URL（可选，默认 http://localhost:8000）。
///
/// 要做的操作：
///     把服务地址、各类周期、缓存目录、版本号集中成常量。
///
/// 返回：
///     静态常量与计算属性（无实例）。
///
/// 为什么：设备端最容易腐化的就是"到处硬编码的地址和周期"，
///         集中一处后，改端口/改节拍只动这个文件。
enum Settings {
    /// 服务端地址：换机器演示时用 MEETCAST_BASE_URL 覆盖，不必改代码
    static let baseURL: URL = {
        let raw = ProcessInfo.processInfo.environment["MEETCAST_BASE_URL"] ?? "http://localhost:8000"
        return URL(string: raw) ?? URL(string: "http://localhost:8000")!
    }()

    /// 设备端版本号（心跳上报，后台设备列表展示）
    static let agentVersion = "1.0.0-macos"

    /// 心跳间隔：服务端 90s 无心跳判离线，30s 一次留足重试余量
    static let heartbeatInterval: TimeInterval = 30

    /// poll 请求超时：服务端 hold 25s，客户端必须大于它，否则会把正常长轮询当失败
    static let pollTimeout: TimeInterval = 40

    /// 日程刷新周期：标牌"下一场"不需要实时，1 分钟足够
    static let scheduleRefreshInterval: TimeInterval = 60

    /// 素材清单同步周期：素材变动低频，5 分钟一次
    static let materialsSyncInterval: TimeInterval = 300

    /// 设备缓存保留天数（PRD F4.4：15 天未使用即清理）
    static let cacheRetentionDays: Int = 15

    /// 页面加载失败后多久重试一次（秒）。
    ///
    /// 为什么要有：兜底页写着"正在重试"，就必须真的在重试。
    /// 会议室屏是长期无人值守的，一次网络抖动若不自愈，屏会一直停在降级页
    /// 直到下一次切屏（可能几小时）——等于派单让人来现场重启。
    static let pageRetryInterval: TimeInterval = 20

    /// 协议层最大单文件（服务端 500MB，这里做客户端预检，避免下载到 99% 才失败）
    static let maxFileBytes: Int64 = 500 * 1024 * 1024

    /// 应用数据目录：~/Library/Application Support/MeetCastDevice
    static var supportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("MeetCastDevice", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// 素材缓存目录
    static var cacheDir: URL {
        let dir = supportDir.appendingPathComponent("cache", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// 会议页 HTML 预缓存目录（F3.3）。
    ///
    /// 为什么单独放在 supportDir 下、而不是 cacheDir/pages：
    ///     素材同步的"清单外清理"与 15 天 LRU 都是遍历 cacheDir 删文件，
    ///     页面缓存一旦放进 cacheDir 的子目录，就会被那两处清理误删
    ///     （实测日志："清理清单外文件：pages"）。目录分开即结构上不可能冲突。
    static var pagesDir: URL {
        let dir = supportDir.appendingPathComponent("pages", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// 凭据文件（device_id / device_key / 校时偏差）
    static var configFile: URL {
        supportDir.appendingPathComponent("device.json")
    }

    /// 本地兜底页（断网/服务挂了时显示，保证不黑屏）
    static func fallbackHTML(reason: String) -> String {
        """
        <!doctype html><html><head><meta charset="utf-8">
        <style>
          html,body{margin:0;height:100%;background:#0B0B12;color:#E9E9F2;
            font-family:-apple-system,"PingFang SC",sans-serif;
            display:flex;flex-direction:column;align-items:center;justify-content:center}
          .dot{width:12px;height:12px;border-radius:50%;background:#7C3AED;margin-bottom:24px;
            animation:pulse 1.6s ease-in-out infinite}
          @keyframes pulse{0%,100%{opacity:.3}50%{opacity:1}}
          h1{font-size:40px;font-weight:600;margin:0 0 12px}
          p{font-size:18px;color:#9A9AB0;margin:0}
        </style></head><body>
          <div class="dot"></div>
          <h1>MeetCast</h1>
          <p>\(reason)</p>
        </body></html>
        """
    }
}

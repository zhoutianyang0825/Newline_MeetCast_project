import CryptoKit
import Foundation

/// 素材本地缓存：预拉取、完整性校验、15 天 LRU（PRD F4.1 / F4.4）。
///
/// 得到的数据：
///     缓存根目录 Settings.cacheDir。
///
/// 要做的操作：
///     按服务端清单下载缺失/变更文件 → 校验 checksum → 统计占用 → 过期与 LRU 清理。
///
/// 返回：
///     单例 MediaCache，供 DeviceAgent 调用。
///
/// 为什么：设备端"断网也能播"的前提是素材真的在本地盘上，
///         而会议室屏磁盘有限（PRD 128G 口径），必须有确定的清理规则。
final class MediaCache {
    static let shared = MediaCache()

    /// 分块读写单位：1MB，避免大文件整包进内存
    private let chunkBytes = 1024 * 1024
    /// 全量哈希上限：超过改为首尾采样（与服务端 files.quick_checksum 口径一致）
    private let fullHashMaxBytes: Int64 = 32 * 1024 * 1024

    private init() {}

    // MARK: - 路径

    /// 某素材在本地的落地路径。
    ///
    /// 得到的数据：
    ///     entry（服务端素材条目，含 material_id / format）。
    ///
    /// 要做的操作：
    ///     拼 cache/<material_id>.<format>。
    ///
    /// 返回：
    ///     file:///.../MeetCastDevice/cache/mat_001.png
    ///
    /// 为什么：文件名用 material_id 而不是原文件名——原文件名可能重名或含特殊字符，
    ///         用 id 才能和清单一一对应、方便按 id 删除。
    func localURL(for entry: MaterialEntry) -> URL {
        Settings.cacheDir.appendingPathComponent("\(entry.materialId).\(entry.format)")
    }

    // MARK: - 会议页 HTML 预缓存（F3.3）

    /// 页面缓存目录（会议页 HTML 存这里）。
    ///
    /// 注意：在 `Settings.pagesDir`（supportDir/pages），**不在** cacheDir 里——
    ///      素材清理只遍历 cacheDir，放一起会被误删。
    var pageCacheDir: URL {
        Settings.pagesDir
    }

    /// 某场会议的本地页面缓存路径。
    ///
    /// 得到的数据：
    ///     meetingId（会议 id，如 "meeting_a3_01_0"）。
    ///
    /// 要做的操作：
    ///     拼 pages/<meeting_id>.html。
    ///
    /// 返回：
    ///     本地文件 URL（不一定存在）。
    ///
    /// 为什么：会议页地址带参数（subject/tagline/attendees…），每场会都不同，
    ///         必须按 meeting_id 分文件存，不能共用一个 page.html。
    func pageCacheURL(meetingId: String) -> URL {
        pageCacheDir.appendingPathComponent("\(meetingId).html")
    }

    /// 预缓存会议页 HTML（F3.3 的"内容预拉取"）。
    ///
    /// 得到的数据：
    ///     url（PREPARE_MEETING.payload.content_url）；
    ///     meetingId（用于命名缓存文件）。
    ///
    /// 要做的操作：
    ///     GET 页面 HTML → 非 200 或空内容视为失败 → 原子写入缓存文件。
    ///
    /// 返回：
    ///     true（缓存成功，断网时可用）/ false（失败，到点仍会在线加载）。
    ///
    /// 为什么：PRD 要求"会前 10 分钟预拉取内容、到点才切屏"。
    ///         只拉素材不拉页面，断网切屏就会白屏；把 HTML 也存下来才算真的"预拉取"。
    func cachePage(url: URL, meetingId: String) async -> Bool {
        do {
            var request = URLRequest(url: url, timeoutInterval: 10)
            request.setValue("text/html,application/xhtml+xml", forHTTPHeaderField: "Accept")
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200, !data.isEmpty else { return false }
            try data.write(to: pageCacheURL(meetingId: meetingId), options: .atomic)
            return true
        } catch {
            return false
        }
    }

    /// 当前缓存占用（MB），上报心跳用。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     遍历缓存目录累加文件大小。
    ///
    /// 返回：
    ///     如 342.5（MB，保留一位小数）。
    ///
    /// 为什么：后台设备列表要展示"这台屏占了多少盘"，也是 15 天 LRU 的观测基线。
    func storageMB() -> Double {
        let fm = FileManager.default
        guard let files = try? fm.contentsOfDirectory(at: Settings.cacheDir, includingPropertiesForKeys: [.fileSizeKey]) else {
            return 0
        }
        var total: Int64 = 0
        for file in files {
            let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            total += Int64(size)
        }
        return (Double(total) / 1024 / 1024 * 10).rounded() / 10
    }

    /// 已在本地且校验通过的文件路径（不通过视为缺失）。
    ///
    /// 得到的数据：
    ///     entry（素材条目，checksum 可为 nil）。
    ///
    /// 要做的操作：
    ///     文件不存在 → nil；有 checksum → 比对哈希；无 checksum → 只要求文件存在且非空。
    ///
    /// 返回：
    ///     可用时返回本地 URL，否则 nil（触发重新下载）。
    ///
    /// 为什么：只看"文件存在"会把半截下载当成完整素材，播放时才发现黑屏；
    ///         必须校验，这也是清单里带 checksum 的意义。
    func verifiedLocalURL(for entry: MaterialEntry) -> URL? {
        let url = localURL(for: entry)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0
        guard size > 0 else { return nil }
        guard let expected = entry.checksum else { return url }
        guard let actual = checksum(of: url) else { return nil }
        return actual == expected ? url : nil
    }

    /// 按服务端清单同步本地缓存。
    ///
    /// 得到的数据：
    ///     entries（GET /api/device/materials 的 items）。
    ///
    /// 要做的操作：
    ///     t1 逐条比对：本地校验通过 → 跳过；否则下载 → 校验 → 通过才算成功；
    ///     t2 下载失败的单条记录日志，不影响其它素材；
    ///     t3 清单外的本地文件删除（服务端已删的素材，设备要跟着清）。
    ///
    /// 返回：
    ///     (下载成功的条数, 失败条数, 当前占用 MB)
    ///
    /// 为什么：同步要"以清单为准"——服务端删了素材，设备不能还留着占盘；
    ///         单条失败不中断整体，避免一个坏文件卡住整轮同步。
    func sync(entries: [MaterialEntry], log: (String) -> Void) async -> (Int, Int, Double) {
        var okCount = 0
        var failCount = 0
        var keep = Set<String>()

        for entry in entries {
            let target = localURL(for: entry)
            keep.insert(target.lastPathComponent)

            if verifiedLocalURL(for: entry) != nil {
                okCount += 1
                continue
            }
            guard let remote = URL(string: entry.url) else {
                failCount += 1
                log("素材地址非法：\(entry.materialId) \(entry.url)")
                continue
            }
            do {
                try await APIClient.shared.download(remote: remote, to: target)
                // 下完立刻校验：半截文件在这里被拦下，不会带病进播放环节
                if verifiedLocalURL(for: entry) != nil {
                    okCount += 1
                    log("素材已缓存：\(entry.name)（\(entry.sizeMb)MB）")
                } else {
                    failCount += 1
                    try? FileManager.default.removeItem(at: target)
                    log("素材校验失败，已丢弃：\(entry.name)")
                }
            } catch {
                failCount += 1
                log("素材下载失败：\(entry.name) — \(error.localizedDescription)")
            }
        }

        // 清单外的文件：服务端已删 → 本地跟着删
        // 只清"文件"，遇到子目录直接跳过——目录归各自模块管，清理逻辑不许递归删目录
        if let files = try? FileManager.default.contentsOfDirectory(
            at: Settings.cacheDir,
            includingPropertiesForKeys: [.isDirectoryKey]
        ) {
            for file in files where !keep.contains(file.lastPathComponent) {
                let isDir = (try? file.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
                if isDir { continue }
                try? FileManager.default.removeItem(at: file)
                log("清理清单外文件：\(file.lastPathComponent)")
            }
        }

        return (okCount, failCount, storageMB())
    }

    /// 按 material_id 删除本地文件（收到 CLEAN_MATERIAL 时用）。
    ///
    /// 得到的数据：
    ///     materialIds（要删的素材 id 列表）。
    ///
    /// 要做的操作：
    ///     在缓存目录里找前缀匹配 <id>. 的文件并删除。
    ///
    /// 返回：
    ///     实际删除的文件数。
    ///
    /// 为什么：专属素材会后必须立刻清（F4.8），不能等 15 天 LRU——
    ///         那些文件可能是客户资料，留在会议室屏上是合规风险。
    func remove(materialIds: [String]) -> Int {
        guard !materialIds.isEmpty else { return 0 }
        let ids = Set(materialIds)
        var removed = 0
        guard let files = try? FileManager.default.contentsOfDirectory(at: Settings.cacheDir, includingPropertiesForKeys: nil) else {
            return 0
        }
        for file in files {
            let base = file.deletingPathExtension().lastPathComponent
            if ids.contains(base) {
                try? FileManager.default.removeItem(at: file)
                removed += 1
            }
        }
        return removed
    }

    /// 15 天 LRU 清理：删掉长期未访问的缓存文件（素材 + 页面缓存）。
    ///
    /// 得到的数据：
    ///     无（读文件 mtime）。
    ///
    /// 要做的操作：
    ///     t1 遍历 cacheDir，跳过子目录，mtime 早于 N 天前 → 删除；
    ///     t2 同样规则扫一遍 pagesDir（会议页 HTML），过期同样清掉。
    ///
    /// 返回：
    ///     删除的文件数（素材 + 页面）。
    ///
    /// 为什么：PRD F4.4 明确"15 天未使用即清理"，会议室屏长期跑不能只增不减；
    ///         用 mtime 而不是 created 是因为重新下载会刷新 mtime，语义更接近"最近使用"。
    ///         只删文件不删目录：目录是模块边界，误删目录会连带干掉别人的数据（曾真出过）。
    func purgeExpired() -> Int {
        let deadline = Date().addingTimeInterval(-Double(Settings.cacheRetentionDays) * 86400)
        var removed = 0

        for dir in [Settings.cacheDir, Settings.pagesDir] {
            guard let files = try? FileManager.default.contentsOfDirectory(
                at: dir,
                includingPropertiesForKeys: [.contentModificationDateKey, .isDirectoryKey]
            ) else { continue }

            for file in files {
                let values = try? file.resourceValues(forKeys: [.contentModificationDateKey, .isDirectoryKey])
                if values?.isDirectory == true { continue }
                let modified = values?.contentModificationDate ?? Date()
                if modified < deadline {
                    try? FileManager.default.removeItem(at: file)
                    removed += 1
                }
            }
        }
        return removed
    }

    // MARK: - 完整性校验

    /// 计算文件哈希，口径与服务端 quick_checksum 一致。
    ///
    /// 得到的数据：
    ///     url（本地文件）。
    ///
    /// 要做的操作：
    ///     ≤32MB → 全量 sha256，返回 "sha256:<hex>"；
    ///     更大 → 首 1MB + 尾 1MB + 字节数 合成，返回 "sha256-partial:<hex>"。
    ///
    /// 返回：
    ///     哈希串；读文件失败返回 nil。
    ///
    /// 为什么：两边算法必须完全一致，否则校验永远不通过、设备陷入无限重下。
    func checksum(of url: URL) -> String? {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }

        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value ?? 0
        var hasher = SHA256()

        if size <= fullHashMaxBytes {
            while true {
                guard let chunk = try? handle.read(upToCount: chunkBytes), !chunk.isEmpty else { break }
                hasher.update(data: chunk)
            }
            return "sha256:" + hasher.finalize().map { String(format: "%02x", $0) }.joined()
        }

        let head = (try? handle.read(upToCount: chunkBytes)) ?? Data()
        hasher.update(data: head)
        try? handle.seek(toOffset: UInt64(max(0, size - Int64(chunkBytes))))
        let tail = (try? handle.read(upToCount: chunkBytes)) ?? Data()
        hasher.update(data: tail)
        hasher.update(data: Data("\(size)".utf8))
        return "sha256-partial:" + hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

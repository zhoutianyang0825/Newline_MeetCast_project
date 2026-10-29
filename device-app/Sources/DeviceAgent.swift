import AppKit
import Foundation

/// 设备 Agent：设备端全部业务逻辑的状态机，UI 只负责展示它。
///
/// 得到的数据：
///     ConfigStore 里的凭据（无凭据则进入绑定流程）。
///
/// 要做的操作：
///     t1 绑定：用输入的密钥换设备档案 → 落盘 → 启动三个循环；
///     t2 心跳循环（30s）：上报状态 + 校时 + 感知解绑；
///     t3 长轮询循环（25s hold）：取指令 → 执行 → 回执；
///     t4 日程循环（60s）与素材同步（300s）：更新"下一场"与本地缓存。
///
/// 返回：
///     @Published 状态供 SwiftUI 绑定（phase / screen / schedule / logs ...）。
///
/// 为什么：把"协议 + 状态机"全放在这里，UI 层不做任何业务判断——
///         将来换到安卓 WebView 壳，也只需照这个状态机重写一遍。
@MainActor
final class DeviceAgent: ObservableObject {

    // MARK: - 对外状态

    /// 设备所处的整体阶段
    enum Phase: Equatable {
        case needBind     // 无凭据 / 密钥失效 → 显示绑定页
        case unbound      // 有凭据但未绑会议室 → 显示未绑定提示
        case ready        // 正常工作中
    }

    /// 当前屏幕上应该显示什么
    enum Screen: Equatable {
        case signage(slot: String)                  // 标牌页
        case meeting(url: URL, meetingId: String)   // 会议页
    }

    @Published var phase: Phase = .needBind
    @Published var screen: Screen = .signage(slot: "default")
    @Published var profile: DeviceProfile?
    @Published var schedule: [ScheduleItem] = []
    @Published var storageMB: Double = 0
    @Published var cachedCount: Int = 0
    @Published var logs: [String] = []
    @Published var isBinding = false
    @Published var bindError: String?

    /// 预备态：已收到 PREPARE_MEETING、正在预拉取，但还没到 switch_at（F3.1 的 MEETING_PREP）
    @Published var isPreparing = false
    /// 降级态：页面加载失败正在显示本地兜底/缓存页（F3.1 的 FALLBACK）
    @Published var loadFailed = false

    /// 当前设备状态（上报给服务端的四态之一，PRD §4.1）
    var deviceState: String {
        if loadFailed { return "FALLBACK" }
        switch screen {
        case .meeting: return "MEETING"
        case .signage: return isPreparing ? "MEETING_PREP" : "IDLE"
        }
    }

    /// 当前播放内容标识（后台展示用）
    var playing: String {
        switch screen {
        case .meeting(_, let id): return "meeting:\(id)"
        case .signage(let slot): return "signage:\(slot)"
        }
    }

    /// 标牌页"下一场"展示对象
    var nextMeeting: ScheduleItem? {
        schedule.first(where: { $0.isNext }) ?? schedule.first(where: { $0.isCurrent })
    }

    // MARK: - 内部

    private let api = APIClient.shared
    private let cache = MediaCache.shared
    private var heartbeatTask: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
    private var scheduleTask: Task<Void, Never>?
    private var switchTask: Task<Void, Never>?

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private var key: String { ConfigStore.shared.config?.deviceKey ?? "" }
    private var deviceId: String { ConfigStore.shared.config?.deviceId ?? "" }

    // MARK: - 生命周期

    /// 进程启动入口：有凭据就直接进工作态，没有就停在绑定页。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     读 ConfigStore → 有配置则 bootstrap，否则 phase = .needBind。
    ///
    /// 返回：
    ///     无（异步过程中更新 @Published）。
    ///
    /// 为什么：设备重启不应该要求人工干预，凭据在就应该"开机即工作"。
    func start() async {
        guard let config = ConfigStore.shared.config else {
            phase = .needBind
            return
        }
        log("检测到已保存凭据：\(config.deviceId)，开始自检")
        await bootstrap()
    }

    /// 绑定：用输入的设备密钥完成"注册"，成功后落盘并进入工作态。
    ///
    /// 得到的数据：
    ///     rawKey（用户输入或粘贴的密钥，如 "dev-key-sh-a3-01-01"）。
    ///
    /// 要做的操作：
    ///     t1 去空格 → 空则报错；
    ///     t2 GET /profile 校验密钥（失败 1002 → 提示密钥无效）；
    ///     t3 通过 → 写入 device.json（device_id 由服务端返回，不靠用户填）；
    ///     t4 bootstrap 启动工作循环。
    ///
    /// 返回：
    ///     无（失败写 bindError）。
    ///
    /// 为什么：device_id 必须由服务端"由密钥反查"给出——让用户手填 id 会出现
    ///         "密钥和 id 不匹配"的经典错误（服务端会直接 2001）。
    func bind(rawKey: String) async {
        let trimmed = rawKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            bindError = "请输入设备密钥"
            return
        }
        isBinding = true
        bindError = nil
        defer { isBinding = false }

        do {
            let profile = try await api.profile(key: trimmed)
            ConfigStore.shared.save(DeviceConfig(
                deviceId: profile.deviceId,
                deviceKey: trimmed,
                clockOffset: offsetFromServerTime(profile.serverTimeUtc)
            ))
            log("绑定成功：\(profile.deviceId)")
            await bootstrap()
        } catch let error as APIError {
            bindError = error.requiresRebind
                ? "密钥无效或设备不存在（\(error.code)）"
                : "绑定失败：\(error.message)"
            log("绑定失败：code=\(error.code) \(error.message)")
        } catch {
            bindError = "无法连接服务端：\(error.localizedDescription)"
            log("绑定失败（网络）：\(error.localizedDescription)")
        }
    }

    /// 清除本地凭据，回到绑定页（设备改绑/换机器时用）。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     停所有循环 → 清配置 → phase = .needBind。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：这是"本地重置"，与服务端解绑是两件事——解绑只清会议室归属，
    ///         本地重置才清密钥，需要人能主动触发。
    func resetLocal() {
        stopLoops()
        ConfigStore.shared.clear()
        profile = nil
        schedule = []
        phase = .needBind
        log("已清除本地凭据")
    }

    /// 启动工作态：自检 → 拉起三个循环 → 决定首屏。
    ///
    /// 得到的数据：
    ///     无（用已落盘的凭据）。
    ///
    /// 要做的操作：
    ///     t1 GET /profile 确认绑定状态；
    ///     t2 未绑定 → phase = .unbound（仍继续心跳，等待管理端绑定）；
    ///     t3 已绑定 → phase = .ready，刷新日程 + 同步素材；
    ///     t4 若当前有进行中的会议，直接切会议页；否则显示标牌；
    ///     t5 启动心跳 / 轮询 / 日程三个循环。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：设备重启时很可能"会已经开了一半"，必须靠日程把屏幕恢复到正确内容，
    ///         而不是傻等下一次 PREPARE_MEETING 指令（那要等到下一场会）。
    func bootstrap() async {
        stopLoops()
        do {
            let profile = try await api.profile(key: key)
            self.profile = profile
            ConfigStore.shared.updateClockOffset(offsetFromServerTime(profile.serverTimeUtc))

            if !profile.bound {
                phase = .unbound
                log("设备未绑定会议室，等待管理端绑定")
            } else {
                // 先算好要显示什么，再把 phase 切到 ready——
                // 否则 ScreenView 会先用初始的标牌页渲染一次，造成明显闪屏
                await refreshSchedule()
                await syncMaterials()
                restoreScreenFromSchedule()
                phase = .ready
                log("已绑定：\(profile.roomName ?? profile.roomId ?? "-")（\(profile.timezone ?? "-")）")
            }

            startLoops()
        } catch let error as APIError where error.requiresRebind {
            log("凭据已失效（\(error.code)），需要重新绑定")
            phase = .needBind
        } catch {
            // 服务端暂时连不上：保留凭据，先显示兜底页，循环会持续重试
            log("自检失败：\(error.localizedDescription)，稍后自动重试")
            startLoops()
        }
    }

    private func startLoops() {
        heartbeatTask = Task { [weak self] in await self?.loopHeartbeat() }
        pollTask = Task { [weak self] in await self?.loopPoll() }
        scheduleTask = Task { [weak self] in await self?.loopSchedule() }
    }

    private func stopLoops() {
        heartbeatTask?.cancel(); heartbeatTask = nil
        pollTask?.cancel(); pollTask = nil
        scheduleTask?.cancel(); scheduleTask = nil
        switchTask?.cancel(); switchTask = nil
    }

    // MARK: - 心跳循环

    /// 心跳循环：30s 一次上报状态并校准时钟。
    ///
    /// 得到的数据：
    ///     无（用当前 deviceState / playing / 缓存占用）。
    ///
    /// 要做的操作：
    ///     t1 POST /heartbeat；
    ///     t2 用返回的 server_time_utc 更新时钟偏差（切屏定时依赖它）；
    ///     t3 凭据失效（1002/2001）→ 停循环回绑定页；
    ///     t4 网络失败 → 记日志，等下一轮（不退出循环）。
    ///
    /// 返回：
    ///     无（循环直到 Task 被取消）。
    ///
    /// 为什么：设备端所有"在线/离线"判定与切屏精度都挂在这个循环上；
    ///         单次失败必须继续重试，否则一次网络抖动就让屏永久离线。
    private func loopHeartbeat() async {
        while !Task.isCancelled {
            do {
                let result = try await api.heartbeat(
                    key: key,
                    deviceId: deviceId,
                    deviceState: deviceState,
                    playing: playing,
                    storageMB: storageMB
                )
                ConfigStore.shared.updateClockOffset(offsetFromServerTime(result.serverTimeUtc))
                if phase == .unbound {
                    // 未绑定时顺带复查：管理端刚绑好，这里能第一时间感知
                    await refreshProfileOnly()
                }
            } catch let error as APIError where error.requiresRebind {
                log("心跳被拒（\(error.code)），回到绑定页")
                phase = .needBind
                stopLoops()
                return
            } catch {
                log("心跳失败：\(error.localizedDescription)")
            }
            try? await Task.sleep(nanoseconds: UInt64(Settings.heartbeatInterval * 1_000_000_000))
        }
    }

    // MARK: - 长轮询循环

    /// 长轮询循环：不断向服务端要指令，拿到就执行并回执。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     t1 POST /poll（服务端 hold 25s，超时返回空）；
    ///     t2 空 → 立即下一轮（这就是"长轮询"的常态）；
    ///     t3 有指令 → handle → ack；
    ///     t4 业务错误 → 短暂退避后重试。
    ///
    /// 返回：
    ///     无（循环直到 Task 被取消）。
    ///
    /// 为什么：空闲时的空返回不是错误，必须立即重连才能保证"指令入队 ≤5s 到达设备"。
    private func loopPoll() async {
        while !Task.isCancelled {
            do {
                let command = try await api.poll(key: key, deviceId: deviceId)
                if command.isEmpty { continue }
                await handle(command)
            } catch let error as APIError where error.requiresRebind {
                log("轮询被拒（\(error.code)），回到绑定页")
                phase = .needBind
                stopLoops()
                return
            } catch {
                log("轮询失败：\(error.localizedDescription)")
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    // MARK: - 日程与素材

    /// 日程刷新循环：60s 一次，驱动"下一场"与开机恢复。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     每 60s 调 refreshSchedule；未绑定态顺便复查绑定。
    ///
    /// 返回：
    ///     无（循环）。
    ///
    /// 为什么：标牌页的"下一场 10:08"是给路过的人看的，误差一分钟以内就够，
    ///         但必须自己会更新——不能指望有指令才刷新。
    private func loopSchedule() async {
        // 素材低频同步：按"日程周期数"计数，避免用取模时间戳那种脆弱的判断
        let syncEveryTicks = max(1, Int(Settings.materialsSyncInterval / Settings.scheduleRefreshInterval))
        var ticks = 0

        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: UInt64(Settings.scheduleRefreshInterval * 1_000_000_000))
            if Task.isCancelled { return }
            await refreshSchedule()
            if phase == .unbound { await refreshProfileOnly() }

            ticks += 1
            if ticks % syncEveryTicks == 0 {
                await syncMaterials()
            }
        }
    }

    /// 只刷新档案（不重启动循环），用于感知"刚被绑定/被解绑"。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     GET /profile，比较 bound 是否变化；变化则切阶段并刷新日程。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：管理端刚绑好，设备不该等到重启才知道；反过来被解绑也要立刻感知。
    private func refreshProfileOnly() async {
        guard let fresh = try? await api.profile(key: key) else { return }
        profile = fresh
        if fresh.bound, phase == .unbound {
            phase = .ready
            log("设备已被绑定到 \(fresh.roomName ?? fresh.roomId ?? "-")")
            await refreshSchedule()
            restoreScreenFromSchedule()
        } else if !fresh.bound, phase == .ready {
            phase = .unbound
            log("设备已被解绑，回到未绑定态")
            switchToSignage()
        }
    }

    /// 拉取日程。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     GET /schedule → 更新 schedule；未绑定则清空。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：日程是标牌"下一场"与开机恢复的唯一依据，集中在这里更新。
    func refreshSchedule() async {
        guard !key.isEmpty else { return }
        do {
            let result = try await api.schedule(key: key)
            schedule = result.items
            if !result.bound, phase == .ready {
                phase = .unbound
            }
        } catch {
            log("日程刷新失败：\(error.localizedDescription)")
        }
    }

    /// 同步素材缓存到本地。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     t1 GET /materials 拿清单；
    ///     t2 交 MediaCache.sync 下载/校验/清理；
    ///     t3 更新占用与条数，并做一次 15 天 LRU。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：预拉取是"断网也能播"的前提；同步完立刻上报占用，
    ///         后台就能看到这台屏真实占了多少盘（PRD F1.3）。
    func syncMaterials() async {
        guard !key.isEmpty else { return }
        do {
            let list = try await api.materials(key: key)
            let (ok, fail, used) = await cache.sync(entries: list.items) { [weak self] line in
                Task { @MainActor in self?.log(line) }
            }
            cachedCount = ok
            storageMB = used
            let purged = cache.purgeExpired()
            if purged > 0 { log("LRU 清理：删除 \(purged) 个超过 \(Settings.cacheRetentionDays) 天未使用的素材") }
            if fail > 0 { log("素材同步完成：成功 \(ok)，失败 \(fail)，占用 \(used)MB") }
        } catch {
            log("素材清单获取失败：\(error.localizedDescription)")
        }
    }

    // MARK: - 指令执行

    /// 执行一条指令。
    ///
    /// 得到的数据：
    ///     command（poll 拿到的指令，类型可能是 PREPARE_MEETING / REPLAY_DEFAULT /
    ///     SWITCH_CONTENT / CLEAN_MATERIAL）。
    ///
    /// 要做的操作：
    ///     按类型分派；执行后 ack（成功 SUCCESS，异常 FAILED），ack 里带执行后状态。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：每条指令都必须有回执（F7.1），否则后台永远停在 SENT；
    ///         分派集中在一处，新增指令类型只加一个 case。
    private func handle(_ command: PollCommand) async {
        guard let commandId = command.commandId, let type = command.type else { return }
        log("收到指令 \(type)（\(command.initiatedBy ?? "-")）id=\(commandId)")
        var status = "SUCCESS"

        switch type {
        case "PREPARE_MEETING":
            await performPrepare(payload: command.payload)
        case "REPLAY_DEFAULT":
            switchTask?.cancel()
            switchToSignage(slot: command.payload?.slot)
            await refreshSchedule()
        case "SWITCH_CONTENT":
            if let raw = command.payload?.contentUrl, let url = URL(string: raw) {
                switchTask?.cancel()
                isPreparing = false
                // 手动切换的 payload 只带 content_url，会议 id 从 URL 的 meeting_id 参数里取
                let mid = command.payload?.meetingId ?? meetingIdFromURL(url) ?? "-"
                screen = .meeting(url: url, meetingId: mid)
                log("手动切换：\(raw)")
            } else {
                status = "FAILED"
            }
        case "CLEAN_MATERIAL":
            let removed = cache.remove(materialIds: command.payload?.materialIds ?? [])
            storageMB = cache.storageMB()
            log("清理专属素材 \(removed) 个，当前占用 \(storageMB)MB")
        default:
            log("未知指令类型 \(type)，已忽略（回执仍报 SUCCESS 以免阻塞队列）")
        }

        do {
            try await api.ack(key: key, commandId: commandId, status: status, deviceState: deviceState)
            log("已回执 \(commandId) → \(status)")
        } catch {
            log("回执失败：\(error.localizedDescription)")
        }
    }

    /// 执行"会前预备"：预拉取素材 + 预加载页面 + 到点切屏。
    ///
    /// 得到的数据：
    ///     payload（含 content_url / switch_at / meeting_id）。
    ///
    /// 要做的操作：
    ///     t1 同步素材清单（把本场专属素材下到本地）；
    ///     t2 计算 switch_at 距现在多少秒（用校准后的服务器时间）；
    ///     t3 已到点 → 立即切；未到点 → 起定时任务等待；
    ///     t4 定时期间若收到新指令会被 cancel（switchTask 覆盖）。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：PRD F3.2 的"双时刻"——会前 10 分钟预备（预拉取，不显示），
    ///         会前 1 分钟切屏。设备必须自己能算这个差值，不能等服务端再发一条。
    private func performPrepare(payload: CommandPayload?) async {
        guard let rawURL = payload?.contentUrl, let url = URL(string: rawURL) else {
            log("PREPARE_MEETING 缺少 content_url")
            return
        }
        let meetingId = payload?.meetingId ?? "-"

        // 进入预备态：后台此刻能看到 MEETING_PREP（F3.1 四态之一）
        isPreparing = true
        log("进入预备态，开始预拉取（\(meetingId)）")

        await syncMaterials()

        // F3.3：把会议页 HTML 也缓存到本地，断网切屏才有内容可显示
        let pageCached = await cache.cachePage(url: url, meetingId: meetingId)
        log(pageCached ? "会议页已预缓存，断网可显示" : "会议页预缓存失败，到点将在线加载")

        let delay = secondsUntil(payload?.switchAt)
        switchTask?.cancel()
        switchTask = Task { [weak self] in
            if delay > 0 {
                await MainActor.run { self?.log("预备完成，将在 \(Int(delay))s 后切屏（\(meetingId)）") }
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            }
            if Task.isCancelled { return }
            await MainActor.run {
                self?.isPreparing = false
                self?.screen = .meeting(url: url, meetingId: meetingId)
                self?.log("已切到会议页：\(meetingId)")
            }
        }
    }

    // MARK: - 屏幕控制

    /// 切到标牌页。
    ///
    /// 得到的数据：
    ///     slot（早/中/晚时段，可选；不传按本地时间推断）。
    ///
    /// 要做的操作：
    ///     取消待执行的切屏定时 → screen = .signage(slot)。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：会议结束必须立刻回标牌（场景 A 11:00 那一步），
    ///         否则屏停在已经结束的会议页上。
    func switchToSignage(slot: String? = nil) {
        isPreparing = false
        loadFailed = false
        screen = .signage(slot: slot ?? localSlot())
    }

    /// 远程页面加载成功：从 FALLBACK 恢复正常。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     若当前处于降级态 → 置回正常并记一条"已恢复"。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：FALLBACK 是四态之一，网络恢复后必须能自动退出来，
    ///         否则后台会一直显示"降级中"，值班的人以为屏幕坏了。
    func reportPageLoaded() {
        guard loadFailed else { return }
        loadFailed = false
        log("页面已恢复，退出 FALLBACK")
    }

    /// 页面加载失败：进入 FALLBACK（心跳会把该状态报给后台）。
    ///
    /// 得到的数据：
    ///     reason（失败原因，如 "The Internet connection appears to be offline."）。
    ///
    /// 要做的操作：
    ///     首次失败置 loadFailed=true 并记日志；重复失败不重复记（防刷屏）。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：设备端"出了事"必须让后台看得见——这正是 F3.1 要求四态而非两态的原因。
    func reportPageFailed(_ reason: String) {
        guard !loadFailed else { return }
        loadFailed = true
        log("页面加载失败，进入 FALLBACK：\(reason)")
    }

    /// 按日程恢复首屏：有进行中的会就直接显示会议页。
    ///
    /// 得到的数据：
    ///     无（用当前 schedule）。
    ///
    /// 要做的操作：
    ///     找 is_current 的会议 → 切会议页；没有 → 标牌。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：设备重启/断网恢复时，屏幕上应该立刻是"现在该显示的内容"，
    ///         而不是空等下一次指令。
    private func restoreScreenFromSchedule() {
        if let current = schedule.first(where: { $0.isCurrent }), let url = URL(string: current.contentUrl) {
            screen = .meeting(url: url, meetingId: current.meetingId)
            log("恢复现场：\(current.subject) 进行中")
        } else {
            switchToSignage()
        }
    }

    /// 本地时段标牌（F3.4 的客户端兜底）。
    ///
    /// 得到的数据：
    ///     无。
    ///
    /// 要做的操作：
    ///     取校准后的本地小时：<12 morning，<18 afternoon，否则 evening。
    ///
    /// 返回：
    ///     "morning" / "afternoon" / "evening"
    ///
    /// 为什么：服务端 REPLAY 指令会带 slot，但开机首次渲染时还没有指令，
    ///         本地按时间推一个，避免标牌页空白。
    private func localSlot() -> String {
        let hour = Calendar.current.component(.hour, from: Date())
        if hour < 12 { return "morning" }
        if hour < 18 { return "afternoon" }
        return "evening"
    }

    // MARK: - 工具

    /// 从会议页 URL 的 query 里取 meeting_id。
    ///
    /// 得到的数据：
    ///     url（会议页地址，如 .../meeting.html?meeting_id=meeting_a3_01_0&subject=...）。
    ///
    /// 要做的操作：
    ///     解析 query，取 meeting_id 参数。
    ///
    /// 返回：
    ///     "meeting_a3_01_0"；取不到返回 nil。
    ///
    /// 为什么：手动切换（SWITCH_CONTENT）的 payload 只带 content_url，
    ///         会议 id 藏在 URL 里；不解出来后台就只能显示 "meeting:-"。
    private func meetingIdFromURL(_ url: URL) -> String? {
        URLComponents(url: url, resolvingAgainstBaseURL: false)?
            .queryItems?
            .first { $0.name == "meeting_id" }?
            .value
    }

    /// 服务器时间与本机的偏差（秒）。
    private func offsetFromServerTime(_ iso: String?) -> TimeInterval {
        guard let iso, let date = Self.isoFormatter.date(from: iso) else {
            return ConfigStore.shared.config?.clockOffset ?? 0
        }
        return date.timeIntervalSinceNow
    }

    /// 距某个 UTC 时刻还有多少秒（用校准后的时间算）。
    private func secondsUntil(_ iso: String?) -> TimeInterval {
        guard let iso, let target = Self.isoFormatter.date(from: iso) else { return 0 }
        let now = ConfigStore.shared.config?.serverNow ?? Date()
        return target.timeIntervalSince(now)
    }

    /// 追加一行日志（同时写屏上列表与本地文件）。
    ///
    /// 得到的数据：
    ///     message（给现场人看的一句话）。
    ///
    /// 要做的操作：
    ///     t1 打时间戳前缀 → 追加到内存列表（保留最近 200 条）；
    ///     t2 同步追加到 device.log（超过 1MB 先清空，避免长跑撑爆磁盘）。
    ///
    /// 返回：
    ///     无。
    ///
    /// 为什么：会议室屏现场排障没有控制台，屏上日志只有当场能看；
    ///         落成文件才能在事后把日志捞出来分析，也是远程诊断的唯一途径。
    func log(_ message: String) {
        let stamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        let line = "[\(stamp)] \(message)"

        logs.append(line)
        if logs.count > 200 {
            logs.removeFirst(logs.count - 200)
        }

        let fileURL = Settings.supportDir.appendingPathComponent("device.log")
        guard let data = (line + "\n").data(using: .utf8) else { return }
        let size = (try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber)?.int64Value ?? 0
        if size > 1_048_576 {
            try? data.write(to: fileURL)   // 超 1MB 直接重写，只保留新日志
            return
        }
        if let handle = try? FileHandle(forWritingTo: fileURL) {
            handle.seekToEndOfFile()
            handle.write(data)
            try? handle.close()
        } else {
            try? data.write(to: fileURL)
        }
    }
}

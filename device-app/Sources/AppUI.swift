import AppKit
import SwiftUI

/// 视觉主题：品牌紫 7C3AED + 深底（与前端 display 页面同一套色）。
///
/// 得到的数据：
///     无。
///
/// 要做的操作：
///     定义 App 内用到的颜色与字号常量。
///
/// 返回：
///     静态常量。
///
/// 为什么：设备屏是"公共场所的大屏"，配色必须和网页端一致，
///         否则从标牌切到会议页会有明显跳色。
enum Theme {
    static let accent = Color(red: 0x7C / 255, green: 0x3A / 255, blue: 0xED / 255)
    static let bg = Color(red: 0x0B / 255, green: 0x0B / 255, blue: 0x12 / 255)
    static let panel = Color(red: 0x14 / 255, green: 0x14 / 255, blue: 0x1E / 255)
    static let text = Color(red: 0xE9 / 255, green: 0xE9 / 255, blue: 0xF2 / 255)
    static let dim = Color(red: 0x9A / 255, green: 0x9A / 255, blue: 0xB0 / 255)
    static let danger = Color(red: 0xF8 / 255, green: 0x71 / 255, blue: 0x71 / 255)
    static let ok = Color(red: 0x4A / 255, green: 0xDE / 255, blue: 0x80 / 255)
}

/// App 根视图：按 Agent 阶段切换"绑定页 / 未绑定页 / 屏幕"。
///
/// 得到的数据：
///     agent（DeviceAgent，@ObservedObject）。
///
/// 要做的操作：
///     根据 phase 渲染对应页面；叠加右上角控制条与可开关的日志面板；
///     首次出现时进入全屏并启动 Agent。
///
/// 返回：
///     SwiftUI 视图。
///
/// 为什么：设备屏没有鼠标键盘，所有"人能干的事"（重置、看日志、全屏）
///         都收在一个默认半透明的小控制条里，不干扰正常显示。
struct RootView: View {
    @ObservedObject var agent: DeviceAgent
    @State private var showLogs = false
    @State private var hoverToolbar = false
    @State private var confirmReset = false

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Theme.bg.ignoresSafeArea()

            content
                .ignoresSafeArea()

            toolbar
                .padding(12)
                .opacity(hoverToolbar ? 1 : 0.28)
                .onHover { hoverToolbar = $0 }

            if showLogs {
                LogPanel(agent: agent) { showLogs = false }
                    .transition(.move(edge: .trailing))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: showLogs)
        .task { await agent.start() }
        .onAppear(perform: enterFullScreen)
        .alert("清除本地凭据？", isPresented: $confirmReset) {
            Button("取消", role: .cancel) {}
            Button("清除", role: .destructive) { agent.resetLocal() }
        } message: {
            Text("清除后本机需要重新输入设备密钥。服务端的绑定关系不受影响。")
        }
    }

    /// 主体内容：三选一
    @ViewBuilder
    private var content: some View {
        switch agent.phase {
        case .needBind:
            BindView(agent: agent)
        case .unbound:
            UnboundView(agent: agent)
        case .ready:
            ScreenView(agent: agent)
        }
    }

    /// 右上角控制条：日志 / 重置 / 全屏
    private var toolbar: some View {
        HStack(spacing: 8) {
            Button {
                showLogs.toggle()
            } label: {
                Image(systemName: "text.alignleft")
            }
            .help("查看运行日志（⌘L）")
            .keyboardShortcut("l", modifiers: .command)

            Button {
                confirmReset = true
            } label: {
                Image(systemName: "arrow.counterclockwise")
            }
            .help("清除本地凭据")

            Button {
                NSApp.keyWindow?.toggleFullScreen(nil)
            } label: {
                Image(systemName: "arrow.up.left.and.arrow.down.right")
            }
            .help("全屏切换（⌃⌘F）")
        }
        .buttonStyle(ToolbarButtonStyle())
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.ultraThinMaterial, in: Capsule())
    }

    /// 进入全屏（设备屏默认就是全屏，不显示桌面）
    private func enterFullScreen() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            guard let window = NSApp.windows.first, !window.styleMask.contains(.fullScreen) else { return }
            window.toggleFullScreen(nil)
        }
    }
}

/// 控制条按钮样式：半透明胶囊里的小图标
struct ToolbarButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(Theme.text)
            .frame(width: 26, height: 22)
            .background(configuration.isPressed ? Theme.accent.opacity(0.5) : Color.white.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

/// 绑定页：设备端"注册"的唯一入口。
///
/// 得到的数据：
///     agent（用于调用 bind / 读 isBinding、bindError）。
///
/// 要做的操作：
///     输入设备密钥 → 点"激活设备" → Agent 校验并落盘；
///     显示服务端地址与本机名，方便现场核对。
///
/// 返回：
///     SwiftUI 视图。
///
/// 为什么：设备端不登录账号，身份就是"设备密钥"；这一页做完，
///         设备就从"一台陌生 Mac"变成"后台可见的一台屏"。
struct BindView: View {
    @ObservedObject var agent: DeviceAgent
    @State private var keyInput = ""

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            brandMark
                .padding(.bottom, 28)

            Text("设备激活")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Theme.text)
                .padding(.bottom, 8)

            Text("输入管理后台下发的设备密钥，激活后本机将自动同步会议日程与素材")
                .font(.system(size: 14))
                .foregroundStyle(Theme.dim)
                .padding(.bottom, 26)

            VStack(spacing: 12) {
                TextField("设备密钥，例如 dev-key-sh-a3-01-01", text: $keyInput)
                    .textFieldStyle(.plain)
                    .font(.system(size: 15, design: .monospaced))
                    .foregroundStyle(Theme.text)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(Theme.panel, in: RoundedRectangle(cornerRadius: 10))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Theme.accent.opacity(0.45), lineWidth: 1)
                    )
                    .frame(width: 420)
                    .onSubmit { Task { await agent.bind(rawKey: keyInput) } }
                    .disabled(agent.isBinding)

                Button {
                    Task { await agent.bind(rawKey: keyInput) }
                } label: {
                    HStack(spacing: 8) {
                        if agent.isBinding {
                            ProgressView().controlSize(.small)
                        }
                        Text(agent.isBinding ? "校验中…" : "激活设备")
                            .font(.system(size: 15, weight: .medium))
                    }
                    .frame(width: 420, height: 42)
                    .background(Theme.accent, in: RoundedRectangle(cornerRadius: 10))
                    .foregroundStyle(.white)
                }
                .buttonStyle(.plain)
                .disabled(agent.isBinding)

                if let error = agent.bindError {
                    Text(error)
                        .font(.system(size: 13))
                        .foregroundStyle(Theme.danger)
                        .frame(width: 420, alignment: .leading)
                }
            }

            Spacer()

            HStack(spacing: 16) {
                Label(Settings.baseURL.absoluteString, systemImage: "server.rack")
                Label(ProcessInfo.processInfo.hostName, systemImage: "desktopcomputer")
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .font(.system(size: 12))
            .foregroundStyle(Theme.dim.opacity(0.8))
            .padding(.bottom, 22)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// 品牌标识：优先用打包进来的 logo，缺失时退回文字
    private var brandMark: some View {
        Group {
            if let image = Self.logoImage {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(height: 64)
            } else {
                HStack(spacing: 10) {
                    Circle().fill(Theme.accent).frame(width: 16, height: 16)
                    Text("MeetCast")
                        .font(.system(size: 26, weight: .bold))
                        .foregroundStyle(Theme.text)
                }
            }
        }
    }

    /// 从 app bundle 的 Resources 读 logo
    private static var logoImage: NSImage? {
        guard let dir = Bundle.main.resourceURL else { return nil }
        let url = dir.appendingPathComponent("logo_icon.png")
        return NSImage(contentsOf: url)
    }
}

/// 未绑定页：有凭据但还没分配会议室（或刚被解绑）。
///
/// 得到的数据：
///     agent（读 profile 的 device_id）。
///
/// 要做的操作：
///     大字展示 device_id（管理员要照着这个在后台绑定）+ 提示等待；
///     每 30s 由心跳循环自动复查，绑好后本页会自己消失。
///
/// 返回：
///     SwiftUI 视图。
///
/// 为什么：PRD A1 要求"开机画面展示 device_id"——现场装机时，
///         工程师就是靠屏幕上这串字号把设备录进后台的。
struct UnboundView: View {
    @ObservedObject var agent: DeviceAgent

    var body: some View {
        VStack(spacing: 18) {
            Spacer()

            Text("本机尚未绑定会议室")
                .font(.system(size: 24, weight: .medium))
                .foregroundStyle(Theme.text)

            Text("请在管理后台完成绑定，本页会自动刷新")
                .font(.system(size: 14))
                .foregroundStyle(Theme.dim)

            VStack(spacing: 6) {
                Text("设备 ID")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.dim)
                Text(agent.profile?.deviceId ?? ConfigStore.shared.config?.deviceId ?? "-")
                    .font(.system(size: 46, weight: .bold, design: .monospaced))
                    .foregroundStyle(Theme.accent)
                    .textSelection(.enabled)
            }
            .padding(.vertical, 26)
            .frame(width: 520)
            .background(Theme.panel, in: RoundedRectangle(cornerRadius: 16))

            HStack(spacing: 8) {
                Circle().fill(Theme.accent).frame(width: 8, height: 8)
                Text("心跳已开启，等待绑定生效")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.dim)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// 屏幕页：真正给人看的内容（标牌 / 会议页）。
///
/// 得到的数据：
///     agent（screen 枚举 + 日程）。
///
/// 要做的操作：
///     按 screen 决定加载哪个 URL；底部细条显示房间与下一场。
///
/// 返回：
///     SwiftUI 视图。
///
/// 为什么：设备 99% 的时间停在这一页，它必须"零交互"——
///         不加任何按钮，只有内容，避免误触。
struct ScreenView: View {
    @ObservedObject var agent: DeviceAgent

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            webContent

            infoBar
                .padding(.horizontal, 16)
                .padding(.bottom, 12)
                .opacity(0.55)
        }
    }

    @ViewBuilder
    private var webContent: some View {
        switch agent.screen {
        case .signage(let slot):
            WebDisplay(
                url: signageURL(slot: slot),
                onFail: { reason in
                    Task { @MainActor in agent.reportPageFailed(reason) }
                },
                onLoad: {
                    Task { @MainActor in agent.reportPageLoaded() }
                }
            )
        case .meeting(let url, let meetingId):
            WebDisplay(
                url: url,
                // F3.3：PREPARE 时预缓存的 HTML，断网/服务挂了就用它渲染
                localFallback: MediaCache.shared.pageCacheURL(meetingId: meetingId),
                onFail: { reason in
                    Task { @MainActor in agent.reportPageFailed(reason) }
                },
                onLoad: {
                    Task { @MainActor in agent.reportPageLoaded() }
                }
            )
        }
    }

    /// 标牌页地址（带房间/时段/下一场参数）
    private func signageURL(slot: String) -> URL {
        var components = URLComponents(
            url: Settings.baseURL.appendingPathComponent("/ui/display/signage.html"),
            resolvingAgainstBaseURL: false
        )!
        var items = [
            URLQueryItem(name: "slot", value: slot),
            URLQueryItem(name: "room", value: agent.profile?.roomName ?? ""),
        ]
        if let next = agent.nextMeeting {
            items.append(URLQueryItem(name: "next", value: "\(next.timeLabel) \(next.subject)"))
            items.append(URLQueryItem(name: "next_subject", value: next.subject))
        }
        components.queryItems = items
        return components.url ?? Settings.baseURL
    }

    /// 底部信息条：房间 + 下一场 + 缓存占用（现场核对用，低透明度不抢内容）
    private var infoBar: some View {
        HStack(spacing: 14) {
            Text(agent.profile?.roomName ?? "-")
                .font(.system(size: 11, weight: .medium))
            if let next = agent.nextMeeting {
                Text(next.isCurrent ? "进行中 \(next.subject)" : "下一场 \(next.timeLabel) \(next.subject)")
                    .font(.system(size: 11))
            }
            Text("缓存 \(String(format: "%.1f", agent.storageMB))MB · \(agent.cachedCount) 个")
                .font(.system(size: 11))
        }
        .foregroundStyle(Theme.dim)
    }
}

/// 运行日志面板：现场排障的唯一线索。
///
/// 得到的数据：
///     agent（logs 数组）。
///
/// 要做的操作：
///     右侧滑出 420 宽面板，倒序展示最近 200 条，自动滚到最新。
///
/// 返回：
///     SwiftUI 视图。
///
/// 为什么：会议室屏没有终端，出问题时工程师只能看这一页——
///         所以每条关键动作（心跳失败、指令、切屏、素材）都必须进日志。
struct LogPanel: View {
    @ObservedObject var agent: DeviceAgent
    let onClose: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("运行日志")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.text)
                Spacer()
                Button(action: onClose) {
                    Image(systemName: "xmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Theme.dim)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)

            Divider().overlay(Theme.dim.opacity(0.2))

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(agent.logs.enumerated()), id: \.offset) { index, line in
                            Text(line)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(Theme.dim)
                                .textSelection(.enabled)
                                .id(index)
                        }
                    }
                    .padding(12)
                }
                .onChange(of: agent.logs.count) { _ in
                    if let last = agent.logs.indices.last {
                        withAnimation { proxy.scrollTo(last, anchor: .bottom) }
                    }
                }
            }
        }
        .frame(width: 420)
        .background(Theme.panel)
        .overlay(Rectangle().frame(width: 1).foregroundStyle(Theme.dim.opacity(0.2)), alignment: .leading)
        .padding(.top, 56)
    }
}

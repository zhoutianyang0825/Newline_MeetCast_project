import AppKit
import SwiftUI

/// App 入口：一个全屏、常亮、无菜单干扰的会议室屏应用。
///
/// 得到的数据：
///     无（启动即读本地凭据）。
///
/// 要做的操作：
///     t1 AppDelegate 里开启"禁止显示器休眠"并隐藏 Dock/菜单栏；
///     t2 WindowGroup 承载 RootView（绑定页或屏幕）；
///     t3 关闭新建窗口的默认菜单项。
///
/// 返回：
///     SwiftUI App。
///
/// 为什么：会议室屏是"无人值守设备"，任何需要点击的行为都算失败；
///         常亮 + 全屏 + 无菜单是设备形态的基本要求（对应 PRD A1 的 kiosk 口径）。
@main
struct MeetCastDeviceApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var agent = DeviceAgent()

    var body: some Scene {
        WindowGroup {
            RootView(agent: agent)
                .frame(minWidth: 1024, minHeight: 640)
                .preferredColorScheme(.dark)
        }
        .windowStyle(.hiddenTitleBar)
        .commands {
            // 设备屏不需要"新建/打开"这类文档菜单，去掉避免误触
            CommandGroup(replacing: .newItem) {}
        }
    }
}

/// App 生命周期代理：常亮、kiosk 形态。
///
/// 得到的数据：
///     系统启动/退出通知。
///
/// 要做的操作：
///     启动时 beginActivity 禁止显示器休眠，并隐藏 Dock 与菜单栏；
///     退出时 endActivity，避免残留能耗声明。
///
/// 返回：
///     无。
///
/// 为什么：macOS 没有安卓的 kiosk 模式，但 presentationOptions + 能耗断言
///         能达到同样效果：屏不黑、Dock 不出来、用户碰不到别的窗口。
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var activityToken: NSObjectProtocol?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 屏幕常亮：会议室屏黑屏 = 故障
        activityToken = ProcessInfo.processInfo.beginActivity(
            options: [.idleDisplaySleepDisabled, .userInitiatedAllowingIdleSystemSleep],
            reason: "MeetCast 会议室屏常亮"
        )
        // 隐藏 Dock 与菜单栏，减少误触（鼠标移到顶部仍会出现，便于调试）
        NSApp.presentationOptions = [.autoHideDock, .autoHideMenuBar]
        NSApp.appearance = NSAppearance(named: .darkAqua)
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let token = activityToken {
            ProcessInfo.processInfo.endActivity(token)
        }
    }

    /// 关掉最后一个窗口即退出（设备屏只有一屏，没有多窗口概念）
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

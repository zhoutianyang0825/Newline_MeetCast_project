import SwiftUI
import WebKit

/// WKWebView 包装：渲染标牌页/会议页，失败时先退本地预缓存页、再退兜底页（绝不黑屏）。
///
/// 得到的数据：
///     url（要渲染的页面地址，指向服务端 /ui/display/*）；
///     localFallback（该会议的本地预缓存 HTML，F3.3 预拉取的产物，可为空）；
///     onFail（加载失败回调，交给上层记日志并上报 FALLBACK）；
///     onLoad（远程页面真正加载成功回调，用来把 FALLBACK 状态改回去）。
///
/// 要做的操作：
///     URL 变化时 load；失败 → 本地缓存 HTML → 兜底页，并每 pageRetryInterval 秒重试原地址；
///     远程页面真正加载成功 → 回调 onLoad 并停止重试。
///
/// 返回：
///     NSViewRepresentable，可直接放进 SwiftUI。
///
/// 为什么：设备端的"屏幕"本质就是一个浏览器。用 WKWebView 而不是自绘，
///         是为了和现有 display 页面（HTML/CSS）共用同一套渲染，换版式只改前端。
struct WebDisplay: NSViewRepresentable {
    let url: URL
    var localFallback: URL? = nil
    var onFail: (String) -> Void = { _ in }
    var onLoad: () -> Void = {}

    func makeCoordinator() -> Coordinator {
        Coordinator(localFallback: localFallback, onFail: onFail, onLoad: onLoad)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.suppressesIncrementalRendering = false
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsMagnification = false
        webView.setValue(false, forKey: "drawsBackground")   // 首帧前不闪白
        webView.load(URLRequest(url: url, timeoutInterval: 12))
        context.coordinator.lastURL = url
        context.coordinator.targetURL = url
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.localFallback = localFallback
        // 只有 URL 真的变了才重载：SwiftUI 会频繁重算 body，无脑 load 会让屏幕一直闪
        guard context.coordinator.lastURL != url else { return }
        context.coordinator.lastURL = url
        context.coordinator.targetURL = url
        context.coordinator.cancelRetry()
        webView.load(URLRequest(url: url, timeoutInterval: 12))
    }

    /// 导航代理：成功回到上层，失败走"缓存页 → 兜底页"两级降级，并持续重试原地址
    final class Coordinator: NSObject, WKNavigationDelegate {
        var lastURL: URL?
        /// 当前应该显示的远程地址（重试时用它，而不是本地缓存页）
        var targetURL: URL?
        var localFallback: URL?
        private let onFail: (String) -> Void
        private let onLoad: () -> Void
        /// 正在显示本地缓存/兜底 HTML：此时 didFinish 不能当成"远程加载成功"
        private var showingLocalHTML = false
        private var retryTimer: Timer?

        init(localFallback: URL?, onFail: @escaping (String) -> Void, onLoad: @escaping () -> Void) {
            self.localFallback = localFallback
            self.onFail = onFail
            self.onLoad = onLoad
        }

        deinit {
            retryTimer?.invalidate()
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            if showingLocalHTML {
                showingLocalHTML = false
                return
            }
            // 远程页面真的回来了：停掉重试，上层把 FALLBACK 改回正常态
            cancelRetry()
            onLoad()
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            handleFailure(webView, error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            handleFailure(webView, error)
        }

        /// 取消待执行的重试（成功加载、或要切到新页面时调用）。
        func cancelRetry() {
            retryTimer?.invalidate()
            retryTimer = nil
        }

        /// 安排一次延迟重试：到点重新加载 targetURL。
        ///
        /// 得到的数据：
        ///     webView（当前这块屏，重试就落在它身上）。
        ///
        /// 要做的操作：
        ///     先取消旧定时器 → 起一个 pageRetryInterval 秒的定时器 → 到点 load 原地址。
        ///
        /// 返回：
        ///     无。
        ///
        /// 为什么：兜底页上写着"正在重试"，代码就必须真的重试；
        ///         单次重试失败会再次进入 handleFailure，自然形成"每 20 秒一次"的自愈循环，
        ///         服务一恢复，下一次重试就能把屏幕救回来（无需人工重启）。
        private func scheduleRetry(_ webView: WKWebView) {
            cancelRetry()
            retryTimer = Timer.scheduledTimer(withTimeInterval: Settings.pageRetryInterval, repeats: false) {
                [weak self, weak webView] _ in
                guard let self, let webView, let target = self.targetURL else { return }
                self.showingLocalHTML = false
                webView.load(URLRequest(url: target, timeoutInterval: 12))
            }
        }

        /// 加载失败 → 先试预缓存会议页，再退兜底页，然后安排重试。
        ///
        /// 得到的数据：
        ///     error（网络中断/超时/服务未启动）。
        ///
        /// 要做的操作：
        ///     t1 回调上报原因（上层据此切 FALLBACK 状态）；
        ///     t2 有本地缓存 HTML → loadHTMLString 并保留 baseURL（CSS 仍尝试走网络）；
        ///     t3 没有缓存 → 显示"正在重试"兜底页；
        ///     t4 无论走 t2 还是 t3，都安排 pageRetryInterval 秒后重试远程地址。
        ///
        /// 返回：
        ///     无。
        ///
        /// 为什么：PRD 要求"断网不黑屏"。会议室屏黑一次，现场就得派人重启；
        ///         而 F3.3 预拉取的 HTML 此刻就是唯一的救命内容。
        private func handleFailure(_ webView: WKWebView, _ error: Error) {
            let message = (error as NSError).localizedDescription
            onFail(message)
            showingLocalHTML = true

            if let local = localFallback,
               let html = try? String(contentsOf: local, encoding: .utf8),
               !html.isEmpty {
                // baseURL 指向服务端：断网时 CSS/JS 拉不到会降级成纯文本，但页面结构还在
                webView.loadHTMLString(html, baseURL: Settings.baseURL)
                scheduleRetry(webView)
                return
            }
            webView.loadHTMLString(Settings.fallbackHTML(reason: "暂时无法连接服务，正在重试…"), baseURL: nil)
            scheduleRetry(webView)
        }
    }
}

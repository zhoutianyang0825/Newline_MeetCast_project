#!/usr/bin/env bash
# MeetCast 设备屏 · macOS App 构建脚本
#
# 为什么不用 Xcode：
#   本机只有 Command Line Tools（无 xcodebuild），但 swiftc 完全可以编译
#   SwiftUI + WebKit 应用；.app 只是一层目录结构 + Info.plist，手工组装即可，
#   再 ad-hoc 签名就能双击运行。省掉 10GB 的完整 Xcode。
#
# 用法：
#   bash build.sh              # 构建到 build/MeetCastScreen.app
#   bash build.sh run          # 构建并启动
#
# 产物：
#   device-app/build/MeetCastScreen.app

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$ROOT")"
APP_NAME="MeetCastScreen"
BUILD_DIR="$ROOT/build"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
ARCH="$(uname -m)"

echo "==> 清理旧产物"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"

echo "==> 编译 Swift 源码（$(ls "$ROOT"/Sources/*.swift | wc -l | tr -d ' ') 个文件）"
# -parse-as-library：@main 入口的必要条件（否则被当成 top-level code）
# -swift-version 5：避免 Swift 6 严格并发检查对 @MainActor 单例的额外约束
swiftc -O \
    -parse-as-library \
    -swift-version 5 \
    -target "${ARCH}-apple-macos13.0" \
    -o "$APP_BUNDLE/Contents/MacOS/$APP_NAME" \
    "$ROOT"/Sources/*.swift

echo "==> 拷贝资源"
if [ -f "$PROJECT_ROOT/brand/logo_icon.png" ]; then
    cp "$PROJECT_ROOT/brand/logo_icon.png" "$APP_BUNDLE/Contents/Resources/"
fi

echo "==> 写 Info.plist"
cat > "$APP_BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>MeetCastScreen</string>
  <key>CFBundleIdentifier</key><string>com.newline.meetcast.screen</string>
  <key>CFBundleName</key><string>MeetCastScreen</string>
  <key>CFBundleDisplayName</key><string>MeetCast 设备屏</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleIconFile</key><string>logo_icon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.business</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
    <key>NSExceptionDomains</key>
    <dict>
      <key>localhost</key>
      <dict>
        <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>
        <key>NSIncludesSubdomains</key><true/>
      </dict>
      <key>127.0.0.1</key>
      <dict>
        <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>
      </dict>
    </dict>
  </dict>
</dict>
</plist>
PLIST

echo "==> ad-hoc 签名"
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null || echo "   (签名失败，仍可本机运行)"

echo ""
echo "构建完成：$APP_BUNDLE"
echo "启动方式：open \"$APP_BUNDLE\""

if [ "${1:-}" = "run" ]; then
    echo "==> 启动 App"
    open "$APP_BUNDLE"
fi

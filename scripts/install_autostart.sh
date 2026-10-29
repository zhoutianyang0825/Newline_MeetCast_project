#!/usr/bin/env bash
# MeetCast 设备屏 · 开机自启安装/卸载（LaunchAgent）
#
# 为什么需要它：
#   macOS 没有安卓的 BOOT_COMPLETED 广播。设备屏要做到"上电即显示"，
#   标准做法是 LaunchAgent：登录时自动拉起 App，崩了自动重启。
#
# 用法（建议你自己在终端执行，会改 ~/Library/LaunchAgents）：
#   bash scripts/install_autostart.sh install     # 安装自启
#   bash scripts/install_autostart.sh status      # 查看状态
#   bash scripts/install_autostart.sh uninstall   # 卸载自启
#
# 注意：
#   1. 先跑一次 device-app/build.sh 生成 .app，本脚本只认已构建产物；
#   2. 装完首次会立即拉起 App；不需要重启系统；
#   3. 卸载后 App 仍可手动 open 启动，只是不再随登录自启。

set -euo pipefail

LABEL="com.newline.meetcast.screen"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT/device-app/build/MeetCastScreen.app"
BIN="$APP_BUNDLE/Contents/MacOS/MeetCastScreen"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

action="${1:-install}"

case "$action" in
  install)
    if [ ! -x "$BIN" ]; then
      echo "找不到可执行文件：$BIN"
      echo "请先构建：bash device-app/build.sh"
      exit 1
    fi
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$BIN</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>
PLIST
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "已安装自启：$PLIST"
    echo "App 已被拉起；崩溃会自动重启（ThrottleInterval 10s 防抖）。"
    ;;
  uninstall)
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "已卸载自启：$PLIST"
    ;;
  status)
    if [ -f "$PLIST" ]; then
      echo "已安装：$PLIST"
      launchctl list | grep "$LABEL" || echo "  （当前未在运行）"
    else
      echo "未安装自启"
    fi
    ;;
  *)
    echo "用法：bash scripts/install_autostart.sh [install|uninstall|status]"
    exit 1
    ;;
esac

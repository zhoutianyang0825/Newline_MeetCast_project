#!/usr/bin/env bash
# 重启 MeetCast 服务（只杀监听进程，绝不动设备 App）
#
# 为什么要单独写这个脚本：
#   在本机踩过一次坑——`lsof -ti :8000 | xargs kill` 会把**连接**过 8000 端口的
#   所有进程都杀掉，包括正在长轮询的设备 App（MeetCastScreen）。表现是"服务重启后
#   App 莫名其妙消失"，且没有任何崩溃报告（因为是被 SIGTERM 正常终止）。
#   正确做法是加 -sTCP:LISTEN，只取监听方。
#
# 适用场景：在自己终端里手动跑（nohup 能留住进程）。
#   若在 AI 会话/CI 里由工具调用执行，工具调用结束会回收整个进程组，
#   nohup 也留不住——那种场景请改用后台任务方式启动服务。

set -euo pipefail

PORT="${MEETCAST_PORT:-8000}"
SERVER_DIR="$(cd "$(dirname "$0")/../server" && pwd)"
LOG="${MEETCAST_LOG:-/tmp/meetcast_server.log}"

echo "==> 1/4 查找监听 :$PORT 的进程（只看 LISTEN，不含客户端连接）"
PIDS="$(lsof -ti ":$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  echo "    发现 ${PIDS}，停止中"
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 1
  STILL="$(lsof -ti ":$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$STILL" ]; then
    echo "    仍在运行，强制停止 ${STILL}"
    # shellcheck disable=SC2086
    kill -9 $STILL 2>/dev/null || true
    sleep 1
  fi
else
  echo "    端口空闲"
fi

echo "==> 2/4 启动服务（日志：${LOG}）"
cd "$SERVER_DIR"
nohup .venv/bin/python -m uvicorn app.main:app --port "$PORT" > "$LOG" 2>&1 &
echo "    PID=$!"

echo "==> 3/4 等待健康检查"
for i in $(seq 1 20); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/api/health" || true)"
  if [ "$CODE" = "200" ]; then
    echo "    就绪（第 ${i} 次探测）"
    break
  fi
  sleep 1
done
if [ "${CODE:-}" != "200" ]; then
  echo "    ✗ 启动失败，最后 20 行日志："
  tail -20 "$LOG"
  exit 1
fi

echo "==> 4/4 状态确认"
echo "    监听进程：$(lsof -ti ":$PORT" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ')"
if pgrep -f "MeetCastScreen.app/Contents/MacOS/MeetCastScreen" > /dev/null; then
  echo "    设备 App：在运行（本次重启未受影响）"
else
  echo "    设备 App：未运行（要演示的话：open device-app/build/MeetCastScreen.app）"
fi

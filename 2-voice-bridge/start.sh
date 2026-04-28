#!/bin/bash
# voice-bridge HTTP 服务启动脚本
# 用法: ./start.sh [stop|restart|status]

set -e
cd "$(dirname "$0")"

mkdir -p logs
PID_FILE="logs/http_server.pid"
LOG_FILE="logs/http_server.out"
PORT="${VOICE_BRIDGE_PORT:-7788}"

cmd="${1:-start}"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "$cmd" in
  start)
    if is_running; then
      echo "已在运行 (PID $(cat $PID_FILE))"
      exit 0
    fi
    # 从 .env 加载配置
    if [ -f .env ]; then
      set -a; . ./.env; set +a
    fi
    # 必填：FISH_AUDIO_API_KEY（Fish Audio S2 TTS），TELEGRAM_BOT_TOKEN（sendVoice）
    if [ -z "${FISH_AUDIO_API_KEY:-}" ]; then
      echo "⚠️  FISH_AUDIO_API_KEY 未设。写到 .env 或 export 一下"
    fi
    # 代理可选：如果你需要走代理才能访问 fish audio / telegram，在 .env 里设 HTTPS_PROXY
    : "${HTTPS_PROXY:=}"; export HTTPS_PROXY
    : "${HTTP_PROXY:=}";  export HTTP_PROXY
    : "${NO_PROXY:=127.0.0.1,localhost}"; export NO_PROXY
    nohup .venv/bin/python server_http.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if is_running; then
      echo "✓ 启动成功 (PID $(cat $PID_FILE)), 端口 $PORT"
      echo "  日志: $LOG_FILE"
      echo "  健康检查: curl http://127.0.0.1:$PORT/health"
    else
      echo "✗ 启动失败，查看 $LOG_FILE"
      tail -20 "$LOG_FILE"
      exit 1
    fi
    ;;
  stop)
    if is_running; then
      kill "$(cat $PID_FILE)"
      rm -f "$PID_FILE"
      echo "✓ 已停止"
    else
      echo "未运行"
    fi
    ;;
  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;
  status)
    if is_running; then
      echo "运行中 (PID $(cat $PID_FILE))"
      curl -s "http://127.0.0.1:$PORT/health" && echo
    else
      echo "未运行"
    fi
    ;;
  *)
    echo "用法: $0 [start|stop|restart|status]"
    exit 1
    ;;
esac

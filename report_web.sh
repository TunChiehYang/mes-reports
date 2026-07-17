#!/usr/bin/env bash
# 生产日报 Web 服务管理脚本
# 用法: bash report_web.sh {start|stop|status}

SCRIPT_DIR="$HOME/.hermes/scripts"
VENV_PYTHON="$SCRIPT_DIR/production-report/bin/python3"
SERVER_SCRIPT="$SCRIPT_DIR/report_server.py"
PID_FILE="/tmp/report_server.pid"
LOG_FILE="/tmp/report_server.log"
PORT=8080

start() {
    if status > /dev/null 2>&1; then
        echo "⚠️  服务已在运行中"
        status
        return
    fi
    echo "🚀 启动 Web 服务..."
    cd "$SCRIPT_DIR"
    nohup "$VENV_PYTHON" "$SERVER_SCRIPT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if status > /dev/null 2>&1; then
        echo "✅ 服务启动成功"
        echo "   访问地址: http://localhost:$PORT"
        echo "   内网地址: http://192.168.101.152:$PORT (需先运行端口转发)"
    else
        echo "❌ 启动失败，查看日志: $LOG_FILE"
    fi
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            rm -f "$PID_FILE"
            echo "🛑 服务已停止 (PID: $PID)"
        else
            rm -f "$PID_FILE"
            echo "⚠️  PID 文件存在但进程已不在，已清理"
        fi
    else
        # 尝试通过端口查找
        PID=$(lsof -ti :$PORT 2>/dev/null | head -1)
        if [ -n "$PID" ]; then
            kill "$PID"
            echo "🛑 服务已停止 (PID: $PID, 通过端口查找)"
        else
            echo "⚠️  未找到运行中的服务"
        fi
    fi
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "✅ 服务运行中 (PID: $PID, 端口: $PORT)"
            echo "   访问: http://localhost:$PORT"
            return 0
        fi
    fi
    # 通过端口检测
    PID=$(lsof -ti :$PORT 2>/dev/null | head -1)
    if [ -n "$PID" ]; then
        echo "✅ 服务运行中 (PID: $PID, 端口: $PORT)"
        echo "   访问: http://localhost:$PORT"
        return 0
    fi
    echo "❌ 服务未运行"
    return 1
}

case "${1:-status}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)       echo "用法: $0 {start|stop|restart|status}" ;;
esac

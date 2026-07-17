#!/usr/bin/env bash
# 7天每日缺口推估
TASK="每日缺口推估"
cd ~/.hermes/scripts
source production-report/bin/activate

run_or_fail() {
    if ! "$@"; then
        python3 notify_failure.py "$TASK" "命令失败: $*"
        exit 1
    fi
}

run_or_fail python3 daily_gap_forecast.py
echo "=== 完成 ==="

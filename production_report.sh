#!/usr/bin/env bash
# 生产日报 Cron 脚本
TASK="生产日报"
cd ~/.hermes/scripts
source production-report/bin/activate

run_or_fail() {
    if ! "$@"; then
        python3 notify_failure.py "$TASK" "命令失败: $*"
        exit 1
    fi
}

echo "=== Step 1: 生成生产日报 ==="
run_or_fail python3 production_report.py

echo "=== Step 2: 发送邮件 ==="
run_or_fail python3 send_daily_email.py

echo "=== 完成 ==="

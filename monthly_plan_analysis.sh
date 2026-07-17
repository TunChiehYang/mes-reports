#!/usr/bin/env bash
# 月计划分析报告 + 邮件投递
TASK="月计划分析"
cd ~/.hermes/scripts
source production-report/bin/activate

run_or_fail() {
    if ! "$@"; then
        python3 notify_failure.py "$TASK" "命令失败: $*"
        exit 1
    fi
}

echo "=== Step 1: 生成月计划分析报告 ==="
run_or_fail python3 monthly_plan_analysis.py

echo "=== Step 2: 发送邮件 ==="
run_or_fail python3 send_monthly_email.py

echo "=== 完成 ==="

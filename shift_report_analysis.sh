#!/usr/bin/env bash
# 当班生产情况 - 邮件自动分析
TASK="当班生产分析"
cd ~/.hermes/scripts
source production-report/bin/activate

run_or_fail() {
    if ! "$@"; then
        python3 notify_failure.py "$TASK" "命令失败: $*"
        exit 1
    fi
}

run_or_fail python3 shift_report_analysis.py
echo "=== 完成 ==="

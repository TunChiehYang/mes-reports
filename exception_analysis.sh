#!/usr/bin/env bash
# 异常工时分析 — 定时任务
TASK="异常工时分析"
cd ~/.hermes/scripts
source production-report/bin/activate

run_or_fail() {
    if ! "$@"; then
        python3 notify_failure.py "$TASK" "命令失败: $*"
        exit 1
    fi
}

echo "=== Step 1: 生成异常工时分析报告 ==="
run_or_fail python3 exception_analysis.py

echo "=== Step 2: 更新互动查询页面 ==="
run_or_fail python3 gen_exception_query.py

echo "=== 完成 ==="

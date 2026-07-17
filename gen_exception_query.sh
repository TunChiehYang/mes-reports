#!/usr/bin/env bash
# 异常工时查询页面更新
TASK="异常工时查询更新"
cd ~/.hermes/scripts
source production-report/bin/activate

run_or_fail() {
    if ! "$@"; then
        python3 notify_failure.py "$TASK" "命令失败: $*"
        exit 1
    fi
}

run_or_fail python3 gen_exception_query.py
echo "=== 完成 ==="

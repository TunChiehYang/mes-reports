#!/usr/bin/env python3
"""
月计划分析报告 — 邮件投递脚本
读取最新的月计划分析 HTML 报告，提取关键信息生成摘要邮件并发送
"""

import re
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime, date
from pathlib import Path

# ============ 配置 ============
OUTPUT_DIR = Path("/mnt/d/outputHTML")
REPORT_URL_BASE = "http://192.168.101.152:8080"

# SMTP
SMTP_HOST = "mail.chiachang.com"
SMTP_PORT = 465
SMTP_USER = "b-mes"
SMTP_PASS = "gmo@1001"
SENDER = "b-mes@chiachang.com"
SENDER_NAME = "MES系统"

# 收件人列表 (可添加多个)
RECIPIENTS = [
    ("prima.yang@chiachang.com", "MES经理"),
    ("meng.wang@chiachang.com", ""),
    ("ryan.lai@chiachang.com", "制造一部经理"),
    ("houlin.song@chiachang.com", "制一部课长"),
    ("yongjun.chen@chiachang.com", "制一部课长"),
    ("jian.zhang@chiachang.com", "制一部课长"),
    ("l.c.cheng@chiachang.com", "总经理"),
]

# ============ 工具函数 ============

def find_latest_report():
    """找最新的月计划分析报告"""
    files = sorted(OUTPUT_DIR.glob("月计划分析_*.html"), reverse=True)
    return files[0] if files else None


def extract_kpi_from_html(html_path):
    """从 HTML 报告中提取关键 KPI"""
    html = html_path.read_text(encoding='utf-8')
    
    # 提取 KPI 数值 (从 value class 的 div)
    values = re.findall(r'class="value">([^<]+)', html)
    
    # 提取日计划达成率
    ach_match = re.search(r'达成率\s*([\d.]+)%', html)
    ach = ach_match.group(1) if ach_match else "—"
    
    # 提取高风险产线列表
    risk_lines = re.findall(r'<td>(N[ABQ]\d+)</td><td>[^<]+</td><td><span[^>]*>高风险</span>', html)
    
    # 提取部门汇总
    dept_summary = []
    dept_rows = re.findall(
        r'<td>(制造[一二]部)</td><td>([^<]+)</td><td>(\d+)</td>\s*<td class="num">([^<]+)</td>\s*<td class="num">([^<]+)</td>\s*<td class="num">([^<]+)</td>\s*<td class="ach">([^<]+)</td>',
        html
    )
    
    return {
        'kpi_values': values if len(values) >= 4 else ["—"] * 4,
        'ach': ach,
        'risk_lines': risk_lines[:8],  # 最多8条
        'dept_summary': dept_rows,
        'file_name': html_path.name,
    }


def build_email_body(kpi, report_url):
    """构建邮件正文"""
    vals = kpi['kpi_values']
    risk_lines = kpi['risk_lines']
    dept_rows = kpi['dept_summary']
    
    # 高风险产线
    risk_text = ""
    if risk_lines:
        risk_text = "\n【高风险产线预警】\n"
        for line in risk_lines:
            risk_text += f"  ⚠ {line}\n"
    else:
        risk_text = "\n【高风险产线预警】\n  当前无高风险产线\n"
    
    # 部门汇总
    dept_text = "\n【部门计划汇总】\n"
    dept_text += f"  {'部门':<8} {'课别':<8} {'月计划':>10} {'日计划':>8} {'日实际':>8} {'达成率':>6}\n"
    dept_text += "  " + "-" * 52 + "\n"
    for d in dept_rows:
        dept, kes, _, mp, dp, da, ach = d
        dept_text += f"  {dept:<8} {kes:<8} {mp:>10} {dp:>8} {da:>8} {ach:>6}\n"
    
    today_str = datetime.now().strftime("%Y年%m月%d日")
    
    body = f"""各位主管，早上好：

{today_str} 月计划 vs 日计划分析报告已生成。

═══════════════════════════════
  📊 关键指标
═══════════════════════════════
  月计划总量：{vals[0]}
  今日日计划：{vals[1]}
  昨日实际产出：{vals[2]}
  高风险产线：{vals[3]} 条
═══════════════════════════════
{risk_text}
{dept_text}

📎 完整报告请查看：
  {report_url}

此致
MES系统 · 自动发送
"""
    return body


def send_email(kpi, report_url):
    """发送邮件"""
    
    subject = f"MES月计划分析报告 - {datetime.now().strftime('%m/%d')}"
    body = build_email_body(kpi, report_url)
    
    msg = MIMEMultipart()
    msg['From'] = f"{SENDER_NAME} <{SENDER}>"
    msg['Subject'] = Header(subject, 'utf-8')
    
    # 收件人
    to_addrs = [addr for addr, _ in RECIPIENTS]
    msg['To'] = ', '.join(to_addrs)
    
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SENDER, to_addrs, msg.as_string())
        server.quit()
        return True, f"发送成功 → {', '.join(to_addrs)}"
    except Exception as e:
        return False, f"发送失败: {e}"


def main():
    print("=" * 50)
    print("  月计划分析报告 — 邮件投递")
    print("=" * 50)
    
    # 1. 查找最新报告
    report = find_latest_report()
    if not report:
        print("[ERROR] 未找到月计划分析报告 HTML")
        sys.exit(1)
    
    print(f"  报告: {report.name}")
    
    # 2. 提取 KPI
    kpi = extract_kpi_from_html(report)
    print(f"  KPI: 月计划={kpi['kpi_values'][0]}, "
          f"日计划={kpi['kpi_values'][1]}, "
          f"风险线={len(kpi['risk_lines'])}条")
    
    # 3. 构建报告 URL
    report_url = f"{REPORT_URL_BASE}/{report.name}"
    
    # 4. 发送
    print(f"  发送邮件...")
    success, msg = send_email(kpi, report_url)
    
    if success:
        print(f"  ✅ {msg}")
    else:
        print(f"  ❌ {msg}")
        sys.exit(1)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

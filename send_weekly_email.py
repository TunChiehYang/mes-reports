#!/usr/bin/env python3
"""
生产周报 — 邮件投递脚本
读取最新的生产周报 HTML，提取关键 KPI 生成摘要邮件并发送
"""

import re
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("/mnt/d/outputHTML")
REPORT_URL_BASE = "http://192.168.101.152:8080"

SMTP_HOST = "mail.chiachang.com"
SMTP_PORT = 465
SMTP_USER = "b-mes"
SMTP_PASS = "gmo@1001"
SENDER = "b-mes@chiachang.com"
SENDER_NAME = "MES系统"

RECIPIENTS = [
    ("prima.yang@chiachang.com", "MES经理"),
    ("meng.wang@chiachang.com", ""),
    ("ryan.lai@chiachang.com", "制造一部经理"),
    ("houlin.song@chiachang.com", "制一部课长"),
    ("yongjun.chen@chiachang.com", "制一部课长"),
    ("jian.zhang@chiachang.com", "制一部课长"),
    ("l.c.cheng@chiachang.com", "总经理"),
]

def find_latest_report():
    files = sorted(OUTPUT_DIR.glob("生产周报_*.html"), reverse=True)
    return files[0] if files else None

def extract_kpi_from_html(html_path):
    html = html_path.read_text(encoding='utf-8')
    
    kpi = {}
    # 提取 KPI
    pairs = re.findall(r'class="label">([^<]+)</div>\s*<div class="value"[^>]*>([^<]+)', html)
    for label, value in pairs:
        label_clean = label.strip()
        if '周计划' in label_clean: kpi['plan'] = value.strip()
        elif '周实际' in label_clean: kpi['actual'] = value.strip()
        elif '周达成率' in label_clean: kpi['ach'] = value.strip()
        elif '产线数' in label_clean: kpi['lines'] = value.strip()
        elif '有效天数' in label_clean: kpi['days'] = value.strip()
    
    # 提取日期范围
    title_match = re.search(r'生产周报 - (\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2})', html)
    if title_match:
        kpi['date_start'] = title_match.group(1)
        kpi['date_end'] = title_match.group(2)
    
    # 提取部门汇总
    dept_rows = re.findall(
        r'<td>(制造[一二]部)</td>\s*<td>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>',
        html
    )
    kpi['dept_rows'] = dept_rows
    
    kpi['file_name'] = html_path.name
    return kpi


def build_email_body(kpi, report_url):
    date_range = f"{kpi.get('date_start', '?')} ~ {kpi.get('date_end', '?')}"
    
    dept_text = ""
    dept_rows = kpi.get('dept_rows', [])
    if dept_rows:
        dept_text = "\n【部门达成率汇总】\n"
        dept_text += f"  {'部门':<8} {'课别':<8} {'周计划':>10} {'周实际':>10} {'达成率':>8}\n"
        dept_text += "  " + "-" * 48 + "\n"
        for d in dept_rows:
            dept, kes, plan, actual, ach = d
            dept_text += f"  {dept:<8} {kes:<8} {plan:>10} {actual:>10} {ach:>8}\n"
    
    body = f"""各位主管，早上好：

生产周报已生成 ({date_range})。

═══════════════════════════════
  📊 关键指标
═══════════════════════════════
  周计划总量：{kpi.get('plan', '—')}
  周实际产出：{kpi.get('actual', '—')}
  周达成率：  {kpi.get('ach', '—')}
  产线数：    {kpi.get('lines', '—')} 条
  有效天数：  {kpi.get('days', '—')} 天
═══════════════════════════════
{dept_text}

📎 完整报告请查看：
  {report_url}

此致
MES系统 · 自动发送
"""
    return body


def send_email(kpi, report_url):
    date_str = f"{kpi.get('date_start', '?')}~{kpi.get('date_end', '?')}"
    subject = f"生产周报 - {date_str}"
    body = build_email_body(kpi, report_url)
    
    msg = MIMEMultipart()
    msg['From'] = f"{SENDER_NAME} <{SENDER}>"
    to_addrs = [addr for addr, _ in RECIPIENTS]
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    server.login(SMTP_USER, SMTP_PASS)
    server.sendmail(SENDER, to_addrs, msg.as_string())
    server.quit()
    return True

def main():
    print("=" * 50)
    print("  生产周报 — 邮件投递")
    print("=" * 50)
    
    report = find_latest_report()
    if not report:
        print("[ERROR] 未找到生产周报 HTML")
        sys.exit(1)
    
    print(f"  报告: {report.name}")
    kpi = extract_kpi_from_html(report)
    report_url = f"{REPORT_URL_BASE}/{report.name}"
    
    print(f"  KPI: 计划={kpi.get('plan','?')}, 实际={kpi.get('actual','?')}, 达成率={kpi.get('ach','?')}")
    
    send_email(kpi, report_url)
    to_addrs = ', '.join(a for a, _ in RECIPIENTS)
    print(f"  ✅ 发送成功 → {to_addrs}")
    return 0

if __name__ == '__main__':
    sys.exit(main())

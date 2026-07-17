#!/usr/bin/env python3
"""临时：处理指定 ID 的当班邮件"""
import sys, imaplib, email, ssl, re
sys.path.insert(0, '/home/primayang/.hermes/scripts')
from shift_report_analysis import parse_records, analyze, generate_html, send_report, OUTPUT_DIR, REPORT_URL_BASE
from email.header import decode_header, make_header
from datetime import datetime

email_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if not email_id:
    print("用法: python3 reprocess_shift.py <email_id>")
    exit(1)

context = ssl.create_default_context()
conn = imaplib.IMAP4_SSL("mail.chiachang.com", 993, timeout=30)
conn.login("b-mes", "gmo@1001")
conn.select("INBOX")

status, data = conn.fetch(str(email_id).encode(), '(RFC822)')
msg = email.message_from_bytes(data[0][1])
date_str = msg['Date']
html_body = ""
for part in msg.walk():
    if part.get_content_type() == 'text/html':
        html_body = part.get_payload(decode=True).decode('utf-8', errors='replace')
        break
conn.logout()

records = parse_records(html_body)
if not records:
    print(f"❌ 邮件 #{email_id} 解析失败")
    exit(1)

print(f"#{email_id} | {date_str} | {len(records)}条产线")

report_text, shift, date_label, dept_data, top5, zero_lines, total_plan, total_done, total_ach = analyze(records, date_str)
html = generate_html(records, dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, date_label, date_str)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
now = datetime.now()
html_name = f"当班分析_{now.strftime('%Y%m%d_%H%M')}_#{email_id}.html"
(OUTPUT_DIR / html_name).write_text(html, encoding='utf-8')
print(f"✅ HTML: {html_name}")
print(f"   http://192.168.101.152:8080/{html_name}")

# Send
to_addrs = send_report(report_text, shift, date_label, html_name)
print(f"✅ 已发送 → {len(to_addrs)}人")

#!/usr/bin/env python3
"""制造二部生产看板 — 基于当班分析数据自动填入"""
import imaplib, email, ssl, re, smtplib, json
from email.header import decode_header, make_header
from collections import defaultdict
from datetime import datetime
from pathlib import Path

IMAP_HOST = "mail.chiachang.com"
USERNAME = "b-mes"
PASSWORD = "gmo@1001"
OUT = Path("/mnt/d/outputHTML")

PLANNED = ['其他计划停线', '计划停机', '管理时间']

def get_latest_shift():
    context = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(IMAP_HOST, 993, timeout=30)
    conn.login(USERNAME, PASSWORD)
    conn.select("INBOX")
    status, messages = conn.search(None, 'ALL')
    all_ids = messages[0].split()
    
    for mid in reversed(all_ids):
        status, data = conn.fetch(mid, '(BODY[HEADER.FIELDS (SUBJECT DATE)])')
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        subject = str(make_header(decode_header(msg['Subject'])))
        if '当班生产情况通知' in subject:
            date_str = msg['Date']
            status, data = conn.fetch(mid, '(RFC822)')
            msg_full = email.message_from_bytes(data[0][1])
            html_body = ""
            for part in msg_full.walk():
                if part.get_content_type() == 'text/html':
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    break
            conn.logout()
            return date_str, html_body
    conn.logout()
    return None, None

def parse_records(html_body):
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_body, re.DOTALL)
    records = []
    for row_html in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
        if len(cells) != 9: continue
        cells_clean = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', '').strip() for c in cells]
        line_id = cells_clean[0]
        if not re.match(r'^N[ABQ]\d+', line_id): continue
        try:
            records.append({
                'line': line_id, 'wo_id': cells_clean[1], 'part_no': cells_clean[2],
                'model': cells_clean[3][:60], 'wo_total': int(cells_clean[4].replace(',', '')),
                'wo_done': int(cells_clean[5].replace(',', '')),
                'shift_plan': int(cells_clean[6].replace(',', '')),
                'shift_done': int(cells_clean[7].replace(',', '')),
                'ach': float(cells_clean[8].replace('%', '').strip()),
            })
        except: continue
    return records

# Get data
date_str, html_body = get_latest_shift()
records = parse_records(html_body)
print(f"解析: {len(records)} 条")

# Filter to 制造二部 only (NQ lines)
dept2 = [r for r in records if r['line'].startswith('NQ')]

# Group by 课室 based on line number
def get_kes(line):
    num = int(re.search(r'NQ(\d+)', line).group(1))
    if 101 <= num <= 115 or 301 <= num <= 310: return '清洗一课'
    if 201 <= num <= 224: return '清洗二课'
    if 401 <= num <= 412 or 501 <= num <= 512: return '清洗三课'
    return '其他'

# Material mapping from model name
def get_material(model):
    m = model.upper()
    if 'COVER' in m or 'BEZEL' in m:
        if 'SUS' in m: return 'SUS'
        if 'AL' in m: return 'AL'
        if 'SECC' in m: return 'SECC'
        if 'SGLC' in m: return 'SGLC'
        if 'DS60' in m: return 'DS60'
        if 'GM55' in m: return 'GM55'
    return '-'

kes_groups = defaultdict(list)
for r in dept2:
    kes_groups[get_kes(r['line'])].append(r)

KES_ORDER = ['清洗一课', '清洗二课', '清洗三课']

# Parse email time for shift label
from email.utils import parsedate_to_datetime
dt = parsedate_to_datetime(date_str)
shift = "白班" if 8 <= dt.hour < 20 else "夜班"
date_label = dt.strftime("%Y-%m-%d %H:%M")

now = datetime.now()

# Build HTML
sections = ""
for kes in KES_ORDER:
    items = kes_groups.get(kes, [])
    if not items:
        sections += f"""<div class="kes-section">
            <div class="kes-title">{kes}<span class="kes-count">0 条</span></div>
            <div class="empty-row">本班无生产数据</div>
        </div>"""
        continue
    
    items.sort(key=lambda x: x['line'])
    total_plan = sum(r['shift_plan'] for r in items)
    total_done = sum(r['shift_done'] for r in items)
    total_ach = total_done / total_plan * 100 if total_plan else 0
    
    rows_html = ""
    for i, r in enumerate(items):
        ach = r['ach']
        ach_color = '#e74c3c' if ach == 0 and r['shift_plan'] > 0 else '#27ae60' if ach >= 60 else '#f39c12'
        bg = '#fff5f5' if ach == 0 and r['shift_plan'] > 0 else ''
        material = get_material(r['model'])
        rows_html += f"""<tr style="background:{bg}">
            <td>{i+1}</td><td>{material}</td><td class="model">{r['model'][:35]}</td>
            <td>{r['part_no'][:20]}</td><td>{r['wo_id'][:22]}</td>
            <td class="n">{r['shift_plan']:,}</td><td class="n">{r['shift_done']:,}</td>
            <td class="n" style="color:{ach_color};font-weight:600">{ach:.1f}%</td>
            <td>{r['wo_done']:,}/{r['wo_total']:,}</td>
        </tr>"""
    
    ach_color = '#e74c3c' if total_ach < 30 else '#f39c12' if total_ach < 60 else '#27ae60'
    
    sections += f"""<div class="kes-section">
        <div class="kes-title">{kes}<span class="kes-count">{len(items)} 条产线</span></div>
        <table>
            <thead><tr><th>#</th><th>材质</th><th>品名</th><th>料号</th><th>工单号</th><th>计划数</th><th>当班完成</th><th>达成率</th><th>工单进度</th></tr></thead>
            <tbody>{rows_html}</tbody>
            <tfoot><tr style="background:#f0f4f8;font-weight:700">
                <td colspan="5">{kes} 合计</td>
                <td class="n">{total_plan:,}</td><td class="n">{total_done:,}</td>
                <td class="n" style="color:{ach_color}">{total_ach:.1f}%</td><td></td>
            </tr></tfoot>
        </table>
    </div>"""

html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta http-equiv="refresh" content="300">
<title>制造二部生产看板 - {date_label}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#1a1a2e;color:#e0e0e0;padding:16px;-webkit-user-select:text;user-select:text}}
.header{{text-align:center;padding:16px;margin-bottom:16px;background:linear-gradient(135deg,#0f3460,#16213e);border-radius:12px}}
.header h1{{font-size:22px;color:#fff}}.header .m{{font-size:13px;color:#8899aa;margin-top:4px}}
.kes-section{{background:#222831;border-radius:10px;margin-bottom:16px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.3)}}
.kes-title{{background:linear-gradient(135deg,#2c3e50,#34495e);padding:12px 20px;font-size:16px;font-weight:700;color:#ecf0f1;display:flex;justify-content:space-between}}
.kes-count{{font-size:13px;color:#95a5a6;font-weight:400}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
thead th{{background:#2c3e50;padding:8px 10px;text-align:left;font-weight:600;color:#bdc3c7;border-bottom:2px solid #3498db;position:sticky;top:0}}
tbody td{{padding:6px 10px;border-bottom:1px solid #2c3e50;color:#ccc}}
tbody tr:hover td{{background:#2c3440}}
tfoot td{{padding:8px 10px;color:#ecf0f1}}
.n{{text-align:right}}.model{{max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.empty-row{{text-align:center;padding:40px;color:#666;font-size:14px}}
.footer{{text-align:center;padding:12px;color:#555;font-size:12px}}
@media(max-width:768px){{body{{padding:8px}}.model{{max-width:120px}}}}
</style>
</head>
<body>
<div class="header">
<h1>制造二部 生产看板</h1>
<div class="m">数据时间: {date_label} | {shift} | {len(dept2)} 条产线 | 自动刷新(5分钟)</div>
</div>
{sections}
<div class="footer">MES 系统 · 自动生成 {now.strftime('%Y-%m-%d %H:%M')} | 数据来源: b-mes邮箱「当班生产情况通知」</div>
</body>
</html>"""

nm = "制二部看板.html"
op = OUT / nm
op.write_text(html, encoding='utf-8')
print(f"✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{nm}")
print(f"\n清洗一课: {len(kes_groups.get('清洗一课',[]))}条 | 清洗二课: {len(kes_groups.get('清洗二课',[]))}条 | 清洗三课: {len(kes_groups.get('清洗三课',[]))}条")
import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])

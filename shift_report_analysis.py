#!/usr/bin/env python3
"""
当班生产情况 — 邮件自动分析
每两小时检查 b-mes 邮箱，发现新"当班生产情况通知"邮件后自动分析并推送
同时生成 HTML 报告到 D:\outputHTML\
"""

import imaplib, email, ssl, re, smtplib, io, base64
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# ============ 中文字体 ============
FONT_CANDIDATES = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei', 'Microsoft YaHei']
for fname in FONT_CANDIDATES:
    if fname in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams['font.family'] = fname
        break
plt.rcParams['axes.unicode_minus'] = False

# ============ 配置 ============
IMAP_HOST = "mail.chiachang.com"
IMAP_PORT = 993
SMTP_HOST = "mail.chiachang.com"
SMTP_PORT = 465
USERNAME = "b-mes"
PASSWORD = "gmo@1001"
SENDER = "b-mes@chiachang.com"
SENDER_NAME = "MES系统"

STATE_FILE = Path("/tmp/mes_shift_last_id.txt")
OUTPUT_DIR = Path("/mnt/d/outputHTML")
REPORT_URL_BASE = "http://192.168.101.152:8080"

RECIPIENTS = [
    ("prima.yang@chiachang.com", "MES经理"),
    ("meng.wang@chiachang.com", ""),
    ("ryan.lai@chiachang.com", "制造一部经理"),
    ("houlin.song@chiachang.com", "制一部课长"),
    ("yongjun.chen@chiachang.com", "制一部课长"),
    ("jian.zhang@chiachang.com", "制一部课长"),
    ("zhiyong.wang@chiachang.com", "生管课长"),
    ("rongrong.guo@chiachang.com", "生管"),
    ("chuang.fan@chiachang.com", "生管"),
    ("mingxing.wang@chiachang.com", "生管"),
    ("linfan.zhang@chiachang.com", "制造二部经理"),
    ("b-mfg210@chiachang.com", "制二统计"),
    ("yaya.fan@chiachang.com", "制一统计"),
    ("l.c.cheng@chiachang.com", "总经理"),
]

# ============ 部门分类 ============
def get_dept(line):
    line = line.strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$', line):
        return ("制造一部", "冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$', line):
        return ("制造一部", "冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$', line):
        return ("制造一部", "冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$', line):
        return ("制造二部", "清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$', line):
        return ("制造二部", "清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$', line):
        return ("制造二部", "清洗三课")
    return ("未分类", "未分类")


def get_latest_shift_email():
    """获取最新一封'当班生产情况通知'邮件 (ID, Date)"""
    context = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
    conn.login(USERNAME, PASSWORD)
    conn.select("INBOX")

    status, messages = conn.search(None, 'ALL')
    all_ids = messages[0].split()

    # 从最新往回找
    for mid in reversed(all_ids):
        status, data = conn.fetch(mid, '(BODY[HEADER.FIELDS (SUBJECT DATE)])')
        raw = data[0][1]
        msg = email.message_from_bytes(raw)
        subject = str(make_header(decode_header(msg['Subject'])))
        if '当班生产情况通知' in subject:
            email_id = int(mid)
            date_str = msg['Date']
            
            # 获取完整内容
            status, data = conn.fetch(mid, '(RFC822)')
            raw = data[0][1]
            msg_full = email.message_from_bytes(raw)
            html_body = ""
            for part in msg_full.walk():
                if part.get_content_type() == 'text/html':
                    html_body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    break
            
            conn.logout()
            return email_id, date_str, html_body

    conn.logout()
    return None, None, None


def parse_records(html_body):
    """从 HTML 表格解析产线记录"""
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_body, re.DOTALL)
    records = []
    for row_html in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL)
        if len(cells) != 9:
            continue
        cells_clean = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', '').strip() for c in cells]
        line_id = cells_clean[0]
        if not re.match(r'^N[ABQ]\d+', line_id):
            continue
        try:
            records.append({
                'line': line_id,
                'wo_id': cells_clean[1],
                'part_no': cells_clean[2],
                'model': cells_clean[3][:60],
                'wo_total': int(cells_clean[4].replace(',', '')),
                'wo_done': int(cells_clean[5].replace(',', '')),
                'shift_plan': int(cells_clean[6].replace(',', '')),
                'shift_done': int(cells_clean[7].replace(',', '')),
                'ach': float(cells_clean[8].replace('%', '').strip()),
            })
        except (ValueError, IndexError):
            continue
    return records


def analyze(records, date_str):
    """分析产线数据，返回报告文本"""
    total_shift_plan = sum(r['shift_plan'] for r in records)
    total_shift_done = sum(r['shift_done'] for r in records)
    total_ach = total_shift_done / total_shift_plan * 100 if total_shift_plan else 0

    # 部门汇总（排除当班完成数为0的产线，不拖累达成率）
    dept_data = defaultdict(lambda: {'plan': 0, 'done': 0, 'lines': 0, 'active_lines': 0})
    for r in records:
        dept, kes = get_dept(r['line'])
        key = f"{dept}-{kes}"
        dept_data[key]['lines'] += 1
        if r['shift_done'] > 0:
            dept_data[key]['plan'] += r['shift_plan']
            dept_data[key]['done'] += r['shift_done']
            dept_data[key]['active_lines'] += 1

    # Top/Bottom
    sorted_ach = sorted(records, key=lambda x: x['ach'], reverse=True)
    top5 = [r for r in sorted_ach if r['shift_plan'] > 0][:5]
    zero_lines = [r for r in records if r['ach'] == 0 and r['shift_plan'] > 0]

    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}

    # 判断班次
    # 从邮件时间推断：上午邮件 → 夜班报告，下午/晚上 → 白班报告
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        shift = "白班" if 8 <= dt.hour < 20 else "夜班"
        date_label = dt.strftime("%m/%d %H:%M")
    except:
        shift = ""
        date_label = date_str

    # 制造一部/二部分别统计
    d1_plan = sum(r['shift_plan'] for r in records if r['line'].startswith(('NA','NB')))
    d1_done = sum(r['shift_done'] for r in records if r['line'].startswith(('NA','NB')))
    d1_ach = d1_done / d1_plan * 100 if d1_plan else 0
    d2_plan = sum(r['shift_plan'] for r in records if r['line'].startswith('NQ'))
    d2_done = sum(r['shift_done'] for r in records if r['line'].startswith('NQ'))
    d2_ach = d2_done / d2_plan * 100 if d2_plan else 0

    report = f"""当班生产情况分析 ({shift})
{'='*50}
邮件时间: {date_label}
解析产线: {len(records)} 条
{'='*50}

【总体概况】
  全厂计划: {total_shift_plan:,} 件 | 完成: {total_shift_done:,} 件 | 达成率: {total_ach:.1f}%

  制造一部(冲压): 计划 {d1_plan:,} | 完成 {d1_done:,} | 达成率 {d1_ach:.1f}%
  制造二部(清洗): 计划 {d2_plan:,} | 完成 {d2_done:,} | 达成率 {d2_ach:.1f}%

【部门达成率】
"""
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['lines'] > 0:
                ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
                bar = '█' * int(ach / 5) + '░' * (20 - int(ach / 5))
                note = f"({d['active_lines']}/{d['lines']}线有产出)" if d['active_lines'] < d['lines'] else f"({d['lines']}线)"
                report += f"  {dept} {kes:<8} {bar} {ach:>5.1f}%  {note}\n"

    report += "\n【达成率 TOP 5】\n"
    for i, r in enumerate(top5, 1):
        report += f"  {i}. {r['line']:<6} {r['model'][:28]:<30} 计划{r['shift_plan']:>6,} → 完成{r['shift_done']:>6,}  {r['ach']:>5.1f}%\n"

    if zero_lines:
        report += f"\n【未开动产线】{len(zero_lines)} 条计划未动\n"
        for r in zero_lines[:5]:
            report += f"  {r['line']:<6} {r['model'][:30]:<32} 计划{r['shift_plan']:>6,}\n"
        if len(zero_lines) > 5:
            report += f"  ... 还有 {len(zero_lines)-5} 条\n"

    report += f"\n📎 {REPORT_URL_BASE}/ | MES自动分析 {datetime.now().strftime('%m/%d %H:%M')}"
    return report, shift, date_label, dept_data, top5, zero_lines, total_shift_plan, total_shift_done, total_ach


def fig_to_base64(fig):
    """matplotlib figure → base64 PNG"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64


def chart_dept_ach(dept_data):
    """部门达成率柱状图"""
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    
    labels = []
    ach_vals = []
    plan_vals = []
    done_vals = []
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['lines'] > 0:
                labels.append(f"{kes}")
                ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
                ach_vals.append(ach)
                plan_vals.append(d['plan'])
                done_vals.append(d['done'])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Left: Achievement rate
    colors = ['#e74c3c' if a < 30 else '#f39c12' if a < 60 else '#27ae60' for a in ach_vals]
    bars = ax1.barh(range(len(labels)), ach_vals, color=colors, edgecolor='white')
    for bar, ach in zip(bars, ach_vals):
        ax1.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2, f'{ach:.1f}%', 
                va='center', fontsize=10, fontweight='bold')
    ax1.set_yticks(range(len(labels)))
    ax1.set_yticklabels(labels, fontsize=10)
    ax1.set_title('部门达成率', fontsize=13, fontweight='bold')
    ax1.set_xlim(0, max(ach_vals) * 1.3 if max(ach_vals) > 0 else 100)
    ax1.grid(axis='x', alpha=0.3)
    ax1.invert_yaxis()

    # Right: Plan vs Done
    x = np.arange(len(labels))
    w = 0.35
    ax2.barh(x + w/2, plan_vals, w, label='计划量', color='#3498db', alpha=0.85)
    ax2.barh(x - w/2, done_vals, w, label='完成量', color='#27ae60', alpha=0.85)
    ax2.set_yticks(x)
    ax2.set_yticklabels(labels, fontsize=10)
    ax2.set_title('计划 vs 完成', fontsize=13, fontweight='bold')
    ax2.legend(fontsize=9, loc='lower right')
    ax2.grid(axis='x', alpha=0.3)
    ax2.invert_yaxis()

    fig.tight_layout()
    return fig_to_base64(fig)


def generate_commentary(dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, records):
    """生成分析摘要与短评"""
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    
    # 总体判断
    if total_ach >= 80:
        overall = "✅ <b>整体表现良好</b>，达成率达标，产线运转正常。"
    elif total_ach >= 50:
        overall = "🟡 <b>整体表现一般</b>，近半数计划未完成，需关注落后产线。"
    elif total_ach >= 20:
        overall = f"🔴 <b>整体达成率偏低 ({total_ach:.1f}%)</b>，大量产线未达预期。"
    else:
        overall = f"🔴 <b>整体达成率极低 ({total_ach:.1f}%)</b>，仅少数产线有产出，需排查原因。"
    
    # 部门分析
    dept_comments = ""
    best_dept = (None, -1)
    worst_dept = (None, 999)
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if not d or d['lines'] == 0:
                continue
            ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
            if ach > best_dept[1]: best_dept = (f"{dept}{kes}", ach)
            if ach < worst_dept[1]: worst_dept = (f"{dept}{kes}", ach)
    
    if best_dept[0]:
        dept_comments += f"<li>🏆 <b>{best_dept[0]}</b> 达成率最高 ({best_dept[1]:.1f}%)</li>"
    if worst_dept[0] and worst_dept[0] != best_dept[0]:
        dept_comments += f"<li>⚠ <b>{worst_dept[0]}</b> 达成率最低 ({worst_dept[1]:.1f}%)</li>"
    
    # 零产出部门
    zero_depts = []
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['plan'] > 0 and d['done'] == 0:
                zero_depts.append(f"{dept}{kes}")
    if zero_depts:
        dept_comments += f"<li>⚫ <b>完全未产出：</b>{'、'.join(zero_depts)}</li>"
    
    # 未开动产线统计
    zero_comment = ""
    if len(zero_lines) > 40:
        zero_comment = f"<b>{len(zero_lines)} 条产线</b>有计划但无产出，占比 {len(zero_lines)/len(records)*100:.0f}%，大面积停产。"
    elif len(zero_lines) > 10:
        zero_comment = f"<b>{len(zero_lines)} 条产线</b>有计划但无产出，需跟进确认原因。"
    elif len(zero_lines) > 0:
        zero_comment = f"<b>{len(zero_lines)} 条产线</b>未开动，数量可控。"
    else:
        zero_comment = "所有计划产线均有产出，运转良好。"
    
    # 亮点产线
    highlight = ""
    if top5 and top5[0]['ach'] > 50:
        highlight = f"表现最佳：<b>{top5[0]['line']}</b>（{top5[0]['model'][:25]}）达成率 {top5[0]['ach']:.1f}%"
    
    # 班次
    shift_note = "白班时段，正常生产节奏。" if shift == "白班" else "夜班时段，关注交班衔接。"
    
    return f"""<div class="summary-box">
    <div class="summary-main">{overall} {shift_note}</div>
    <div class="summary-detail">
        <ul>{dept_comments}</ul>
        <p style="margin-top:8px">📌 {zero_comment}</p>
        {f'<p style="margin-top:4px;color:#27ae60">🌟 {highlight}</p>' if highlight else ''}
    </div>
</div>"""


def generate_html(records, dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, date_label, email_date):
    """生成 HTML 分析报告"""
    now = datetime.now()
    
    # Chart
    chart_img = chart_dept_ach(dept_data)
    
    # Department table rows
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    
    dept_rows = ""
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['lines'] > 0:
                ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
                color = '#e74c3c' if ach < 30 else '#f39c12' if ach < 60 else '#27ae60'
                active_info = f"（{d['active_lines']}/{d['lines']}线有产出）" if d['active_lines'] < d['lines'] else ""
                dept_rows += f"""<tr>
                    <td>{dept}</td><td>{kes}</td><td>{d['lines']}{active_info}</td>
                    <td class="num">{d['plan']:,}</td><td class="num">{d['done']:,}</td>
                    <td class="ach" style="color:{color}">{ach:.1f}%</td>
                </tr>"""
    
    # Line detail table — 按部门分组，达成率排序
    line_rows = ""
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    
    # 分组
    groups = defaultdict(list)
    for r in records:
        dept, kes = get_dept(r['line'])
        groups[(dept, kes)].append(r)
    
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = (dept, kes)
            if key not in groups:
                continue
            lines = sorted(groups[key], key=lambda x: x['ach'], reverse=True)
            active = [r for r in lines if r['shift_done'] > 0]
            g_plan = sum(r['shift_plan'] for r in active)
            g_done = sum(r['shift_done'] for r in active)
            g_ach = g_done / g_plan * 100 if g_plan else 0
            g_color = '#e74c3c' if g_ach < 30 else '#f39c12' if g_ach < 60 else '#27ae60'
            
            # 部门分组标题行
            active_note = f"（{len(active)}/{len(lines)}线有产出）" if len(active) < len(lines) else ""
            line_rows += f"""<tr style="background:#f0f4f8;font-weight:700">
                <td colspan="2">{dept} · {kes}</td>
                <td>{len(lines)} 条产线{active_note}</td>
                <td class="num">{g_plan:,}</td>
                <td class="num">{g_done:,}</td>
                <td class="ach" style="color:{g_color}">{g_ach:.1f}%</td>
            </tr>"""
            
            for r in lines:
                ach = r['ach']
                color = '#e74c3c' if ach == 0 and r['shift_plan'] > 0 else '#27ae60' if ach >= 60 else '#f39c12'
                bg = '#fff5f5' if ach == 0 and r['shift_plan'] > 0 else ''
                line_rows += f"""<tr style="background:{bg}">
                    <td>{r['line']}</td><td>{r['model'][:35]}</td><td>{r['wo_id'][:25]}</td>
                    <td class="num">{r['shift_plan']:,}</td><td class="num">{r['shift_done']:,}</td>
                    <td class="ach" style="color:{color}">{ach:.1f}%</td>
                </tr>"""
    
    ach_color = '#e74c3c' if total_ach < 30 else '#f39c12' if total_ach < 60 else '#27ae60'
    
    # 制造一部/制造二部分别统计
    dept1_plan = sum(r['shift_plan'] for r in records if r['line'].startswith(('NA','NB')))
    dept1_done = sum(r['shift_done'] for r in records if r['line'].startswith(('NA','NB')))
    dept1_ach = dept1_done / dept1_plan * 100 if dept1_plan else 0
    dept1_active = sum(1 for r in records if r['line'].startswith(('NA','NB')) and r['shift_done'] > 0)
    dept1_total = sum(1 for r in records if r['line'].startswith(('NA','NB')))
    
    dept2_plan = sum(r['shift_plan'] for r in records if r['line'].startswith('NQ'))
    dept2_done = sum(r['shift_done'] for r in records if r['line'].startswith('NQ'))
    dept2_ach = dept2_done / dept2_plan * 100 if dept2_plan else 0
    dept2_active = sum(1 for r in records if r['line'].startswith('NQ') and r['shift_done'] > 0)
    dept2_total = sum(1 for r in records if r['line'].startswith('NQ'))
    
    d1c = '#e74c3c' if dept1_ach < 30 else '#f39c12' if dept1_ach < 60 else '#27ae60'
    d2c = '#e74c3c' if dept2_ach < 30 else '#f39c12' if dept2_ach < 60 else '#27ae60'
    
    # 生成摘要短评
    commentary = generate_commentary(dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, records)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>当班生产分析 - {date_label} {shift}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'WenQuanYi Zen Hei', 'Microsoft YaHei', sans-serif;
        background: #f0f2f5; color: #333; padding: 20px;
        -webkit-user-select: text; user-select: text;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    .header {{
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        color: white; padding: 24px 36px; border-radius: 14px; margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
    }}
    .header h1 {{ font-size: 24px; margin-bottom: 4px; }}
    .header .meta {{ font-size: 13px; opacity: 0.8; }}
    .kpi-row {{ display: flex; gap: 14px; margin-bottom: 20px; }}
    .kpi-card {{
        flex: 1; background: white; border-radius: 12px; padding: 18px 22px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06); text-align: center;
    }}
    .kpi-card .label {{ font-size: 13px; color: #888; }}
    .kpi-card .value {{ font-size: 28px; font-weight: 700; margin: 4px 0; }}
    .kpi-card .sub {{ font-size: 12px; color: #aaa; }}
    .section {{
        background: white; border-radius: 12px; padding: 22px 26px;
        margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.06);
    }}
    .section h2 {{ font-size: 17px; color: #1a1a2e; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 2px solid #3498db; }}
    .chart-img {{ max-width: 100%; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    thead th {{ background: #f8f9fa; padding: 9px 10px; text-align: left; font-weight: 600; border-bottom: 2px solid #dee2e6; }}
    tbody td {{ padding: 7px 10px; border-bottom: 1px solid #f1f3f5; }}
    tbody tr:hover {{ background: #f8f9ff; }}
    .num {{ text-align: right; }}
    .ach {{ text-align: right; font-weight: 600; }}
    .table-wrap {{ max-height: 550px; overflow-y: auto; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} .kpi-row {{ flex-wrap: wrap; }} }}
    .badge-shift {{
        display: inline-block; padding: 3px 14px; border-radius: 14px; font-size: 14px;
        margin-left: 10px; font-weight: 600;
    }}
    .badge-day {{ background: #f39c12; color: white; }}
    .badge-night {{ background: #34495e; color: #ecf0f1; }}
    .summary-box {{
        background: linear-gradient(135deg, #f8f9ff, #eef1f8);
        border-left: 5px solid #3498db; border-radius: 10px;
        padding: 18px 24px; margin-bottom: 20px; line-height: 1.7;
    }}
    .summary-main {{ font-size: 15px; color: #1a1a2e; margin-bottom: 8px; }}
    .summary-detail {{ font-size: 13px; color: #555; }}
    .summary-detail ul {{ list-style: none; padding: 0; }}
    .summary-detail li {{ padding: 3px 0; }}
    .dept-section {{ margin-bottom: 16px; }}
    .dept-label {{ font-size: 15px; font-weight: 700; color: #2c3e50; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }}
    .dept-info {{ font-size: 12px; color: #95a5a6; font-weight: 400; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>🏭 当班生产情况分析
        <span class="badge-shift {'badge-day' if shift == '白班' else 'badge-night'}">{shift}</span>
    </h1>
    <div class="meta">
        邮件时间: {date_label} &nbsp;|&nbsp; 解析产线: {len(records)} 条 &nbsp;|&nbsp; 生成: {now.strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>

<div class="dept-section">
<div class="dept-label">🏭 制造一部（冲压）<span class="dept-info">{dept1_active}/{dept1_total}线有产出</span></div>
<div class="kpi-row">
    <div class="kpi-card"><div class="label">📋 计划</div><div class="value" style="color:#3498db">{dept1_plan:,}</div><div class="sub">件</div></div>
    <div class="kpi-card"><div class="label">✅ 完成</div><div class="value" style="color:#27ae60">{dept1_done:,}</div><div class="sub">件</div></div>
    <div class="kpi-card"><div class="label">📈 达成率</div><div class="value" style="color:{d1c}">{dept1_ach:.1f}%</div><div class="sub">{'🔴预警' if dept1_ach<30 else '🟡偏低' if dept1_ach<60 else '🟢正常'}</div></div>
</div>
</div>

<div class="dept-section">
<div class="dept-label">🏗️ 制造二部（清洗）<span class="dept-info">{dept2_active}/{dept2_total}线有产出</span></div>
<div class="kpi-row">
    <div class="kpi-card"><div class="label">📋 计划</div><div class="value" style="color:#3498db">{dept2_plan:,}</div><div class="sub">件</div></div>
    <div class="kpi-card"><div class="label">✅ 完成</div><div class="value" style="color:#27ae60">{dept2_done:,}</div><div class="sub">件</div></div>
    <div class="kpi-card"><div class="label">📈 达成率</div><div class="value" style="color:{d2c}">{dept2_ach:.1f}%</div><div class="sub">{'🔴预警' if dept2_ach<30 else '🟡偏低' if dept2_ach<60 else '🟢正常'}</div></div>
</div>
</div>

<div class="kpi-row" style="margin-top:8px">
    <div class="kpi-card" style="background:#f8f9fa"><div class="label">📊 全厂合计</div><div class="value" style="color:#2c3e50;font-size:20px">{total_plan:,} / {total_done:,}</div><div class="sub">计划/完成 | 达成率 {total_ach:.1f}% | 未开动 {len(zero_lines)}条</div></div>
</div>

{commentary}

<div class="section">
    <h2>📊 部门达成率 & 计划/完成对比</h2>
    <img class="chart-img" src="data:image/png;base64,{chart_img}" alt="部门对比">
</div>

<div class="grid-2">
    <div class="section">
        <h2>📋 部门汇总</h2>
        <table>
            <thead><tr><th>部门</th><th>课别</th><th>产线</th><th>计划</th><th>完成</th><th>达成率</th></tr></thead>
            <tbody>{dept_rows}</tbody>
        </table>
    </div>
    <div class="section">
        <h2>🏆 TOP 5 产线</h2>
        <table>
            <thead><tr><th>产线</th><th>机型</th><th>计划</th><th>完成</th><th>达成率</th></tr></thead>
            <tbody>
""" + "".join(
    f"<tr><td>{r['line']}</td><td>{r['model'][:35]}</td><td class='num'>{r['shift_plan']:,}</td><td class='num'>{r['shift_done']:,}</td><td class='ach' style='color:#27ae60'>{r['ach']:.1f}%</td></tr>"
    for r in top5
) + f"""</tbody>
        </table>
    </div>
</div>

<div class="section">
    <h2>🔍 产线明细（按部门分组 · 达成率排序）</h2>
    <div class="table-wrap">
    <table>
        <thead><tr><th>产线</th><th>机型</th><th>工单号</th><th>计划</th><th>完成</th><th>达成率</th></tr></thead>
        <tbody>{line_rows}</tbody>
    </table>
    </div>
</div>

</div>
</body>
</html>"""
    return html


def send_report(report_text, shift, date_label, html_name=""):
    """发送分析邮件"""
    subject = f"[测试]当班生产分析 - {date_label} {shift}"
    
    # 追加 HTML 报告链接
    if html_name:
        report_text += f"\n\n📊 完整 HTML 报告: {REPORT_URL_BASE}/{html_name}"
    
    msg = MIMEMultipart()
    msg['From'] = f"{SENDER_NAME} <{SENDER}>"
    to_addrs = [addr for addr, _ in RECIPIENTS]
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(report_text, 'plain', 'utf-8'))

    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    server.login(USERNAME, PASSWORD)
    server.sendmail(SENDER, to_addrs, msg.as_string())
    server.quit()
    return to_addrs


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 检查新邮件...")

    # 读取上次处理 ID
    last_id = 0
    if STATE_FILE.exists():
        last_id = int(STATE_FILE.read_text().strip())

    # 获取最新邮件
    email_id, date_str, html_body = get_latest_shift_email()
    if email_id is None:
        print("  未找到'当班生产情况通知'邮件")
        return 0

    # 检查是否新邮件
    if email_id <= last_id:
        print(f"  无新邮件 (最新 #{email_id}, 已处理 #{last_id})")
        return 0

    # 解析
    records = parse_records(html_body)
    if not records:
        print(f"  ⚠ 邮件 #{email_id} 解析失败 (0条记录)")
        STATE_FILE.write_text(str(email_id))
        return 1

    # 分析
    print(f"  新邮件 #{email_id} | {len(records)}条产线 → 分析中...")
    report_text, shift, date_label, dept_data, top5, zero_lines, total_plan, total_done, total_ach = analyze(records, date_str)

    # 生成 HTML 报告
    print(f"  生成 HTML 报告...")
    html = generate_html(records, dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, date_label, date_str)
    
    # 保存 HTML
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    html_name = f"当班分析_{now.strftime('%Y%m%d_%H%M')}.html"
    html_path = OUTPUT_DIR / html_name
    html_path.write_text(html, encoding='utf-8')
    print(f"  ✅ HTML: {html_path} ({html_path.stat().st_size/1024:.0f} KB)")

    # 发送邮件（含 HTML 链接）
    to_addrs = send_report(report_text, shift, date_label, html_name)
    print(f"  ✅ 已发送 → {', '.join(to_addrs)}")

    # 更新状态
    STATE_FILE.write_text(str(email_id))
    return 0


if __name__ == '__main__':
    import sys
    ret = main()
    import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])
    sys.exit(ret)

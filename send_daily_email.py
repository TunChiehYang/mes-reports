#!/usr/bin/env python3
"""生产日报邮件 — 从 PG plan_daily_detail（Oracle GET_VALID_WOW 直连）提取前一天完整数据
白班+夜班，SMTP 走内网 192.168.0.188:465
用法: python3 send_daily_email.py [YYYY-MM-DD]   # 缺省=昨天（服务器时间-1）
"""
import re, sys, smtplib, urllib.request
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime, timedelta
from pathlib import Path

REPORT_URL_BASE = "http://10.2.20.127:8080"

SMTP_HOST = "192.168.0.188"; SMTP_PORT = 465
SMTP_USER = "b-mes"; SMTP_PASS = "gmo@1001"
SENDER = "b-mes@chiachang.com"; SENDER_NAME = "MES系统"

# 测试阶段：仅发 prima.yang（KPI 定稿后放开全量名单）
RECIPIENTS = [
    ("prima.yang@chiachang.com", "MES经理"),
]

import psycopg2
import psycopg2.extras
PG = dict(host='10.2.20.127', port=5432, user='postgres',
          password='Chia@1234', dbname='mes_plan')

# 目标日期：缺省 = 昨天（服务器时区 Asia/Shanghai）
target = sys.argv[1] if len(sys.argv) > 1 else (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

conn = psycopg2.connect(**PG)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
# 前一天完整数据（白班+夜班），按 (line_id, wo_id, clas_type) 去重取最新 sync_time
cur.execute("""
    SELECT DISTINCT ON (line_id, wo_id, clas_type) *
    FROM plan_daily_detail
    WHERE tplan_start = %s
    ORDER BY line_id, wo_id, clas_type, sync_time DESC
""", (target,))
rows = cur.fetchall()
cur.close()
conn.close()
if not rows:
    print(f"⚠ {target} 无数据（可能是周末/未排产），跳过邮件")
    sys.exit(0)

dt = datetime.strptime(target, '%Y-%m-%d')
date_str = dt.strftime('%Y年%m月%d日')
subject_date = dt.strftime('%m/%d')

df = pd.DataFrame(rows).fillna('')
df['wo_plan_qty'] = pd.to_numeric(df['wo_plan_qty'], errors='coerce').fillna(0).astype(int)
df['actual_qty'] = pd.to_numeric(df['actual_qty'], errors='coerce').fillna(0).astype(int)
df['PLANQTY'] = df['wo_plan_qty']
df['AUTOQTY'] = df['actual_qty']
df_norm = df[df['actual_qty'] > 0].copy()  # 有产出 = 有效生产

# Overall
total_plan = int(df_norm['PLANQTY'].sum())
total_actual = int(df_norm['AUTOQTY'].sum())
total_ach = total_actual / total_plan * 100 if total_plan else 0

# By dept+shift
d1 = df_norm[df_norm['line_id'].str.match(r'^(NA|NB)')]
d2 = df_norm[df_norm['line_id'].str.match(r'^NQ')]

shift_plan = {}; shift_act = {}
for label, data in [('d1', d1), ('d2', d2)]:
    for shift in ['白班', '夜班']:
        sub = data[data['clas_type'] == shift]
        shift_plan[f'{label}_{shift}'] = int(sub['PLANQTY'].sum())
        shift_act[f'{label}_{shift}'] = int(sub['AUTOQTY'].sum())

# Line ranking
line_ach = df_norm.groupby('line_id').agg(
    plan=('PLANQTY','sum'), actual=('AUTOQTY','sum'),
    model=('model_no', lambda x: '/'.join(sorted(set(str(m) for m in x if str(m).strip()))[:40]))
).reset_index()
line_ach['ach'] = (line_ach['actual'] / line_ach['plan'].replace(0,1) * 100).clip(0,200)
line_ach = line_ach[line_ach['plan'] > 0].sort_values('ach', ascending=False)

d1_lines = line_ach[line_ach['line_id'].str.match(r'^(NA|NB)')]
d2_lines = line_ach[line_ach['line_id'].str.match(r'^NQ')]

def fmt_top(items, n=3):
    lines = []
    for _, r in items.head(n).iterrows():
        lines.append(f"    {r['line_id']} | {str(r['model'])[:20]} | 计划{int(r['plan']):,} 实际{int(r['actual']):,} 达成率{r['ach']:.1f}%")
    return '\n'.join(lines)

# 报告链接：匹配 生产日报PG_{YYYYMMDD}_*.html
def report_link(date8):
    try:
        idx = urllib.request.urlopen(f"{REPORT_URL_BASE}/index.html", timeout=10).read().decode('utf-8', 'ignore')
        files = sorted(set(re.findall(rf'生产日报PG_{date8}_\d+\.html', idx)))
        if files:
            return f"{REPORT_URL_BASE}/{files[-1]}"
    except Exception as e:
        print(f"[warn] 取报告链接失败: {e}")
    return f"{REPORT_URL_BASE}/"

link = report_link(target.replace('-', ''))

# Build email
body = f"""各位主管，早上好：

{date_str} 生产日报已生成（前一日白班+夜班完整数据）。

═══════════════════════════════
  📊 关键指标
═══════════════════════════════
  全厂: 计划 {total_plan:,} / 实际 {total_actual:,} / 达成率 {total_ach:.1f}%

  🏭 制造一部（冲压）
    白班 计划 {shift_plan['d1_白班']:,} 实际 {shift_act['d1_白班']:,}
    夜班 计划 {shift_plan['d1_夜班']:,} 实际 {shift_act['d1_夜班']:,}

  🏗️ 制造二部（清洗+组装）
    白班 计划 {shift_plan['d2_白班']:,} 实际 {shift_act['d2_白班']:,}
    夜班 计划 {shift_plan['d2_夜班']:,} 实际 {shift_act['d2_夜班']:,}
═══════════════════════════════

【🏭 制造一部 达成率排名 TOP/BOTTOM】
  TOP 3:
{fmt_top(d1_lines.head(3), 3)}
  BOTTOM 3:
{fmt_top(d1_lines.tail(3), 3)}

【🏗️ 制造二部 达成率排名 TOP/BOTTOM】
  TOP 3:
{fmt_top(d2_lines.head(3), 3)}
  BOTTOM 3:
{fmt_top(d2_lines.tail(3), 3)}

📎 完整日报：{link}

此致 · MES系统自动发送
"""

# Send
msg = MIMEMultipart()
msg['From'] = f"{SENDER_NAME} <{SENDER}>"
msg['To'] = ', '.join(a for a,_ in RECIPIENTS)
msg['Subject'] = Header(f"生产日报 - {subject_date}", 'utf-8')
msg.attach(MIMEText(body, 'plain', 'utf-8'))

server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
server.login(SMTP_USER, SMTP_PASS)
server.sendmail(SENDER, [a for a,_ in RECIPIENTS], msg.as_string())
server.quit()
print(f"✅ 邮件已发送: {', '.join(a for a,_ in RECIPIENTS)} | 日期 {target}")

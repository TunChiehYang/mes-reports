#!/usr/bin/env python3
"""生产日报邮件 — 从 CSV 直接提取数据"""
import re, sys, smtplib, pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("/mnt/d/outputHTML")
DAILY_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
REPORT_URL_BASE = "http://192.168.101.152:8080"

SMTP_HOST = "mail.chiachang.com"; SMTP_PORT = 465
SMTP_USER = "b-mes"; SMTP_PASS = "gmo@1001"
SENDER = "b-mes@chiachang.com"; SENDER_NAME = "MES系统"

RECIPIENTS = [
    ("prima.yang@chiachang.com", "MES经理"), ("meng.wang@chiachang.com", ""),
    ("ryan.lai@chiachang.com", "制造一部经理"),
    ("houlin.song@chiachang.com", "制一部课长"),
    ("yongjun.chen@chiachang.com", "制一部课长"),
    ("jian.zhang@chiachang.com", "制一部课长"),
    ("zhiyong.wang@chiachang.com", "生管课长"),
    ("rongrong.guo@chiachang.com", "生管"), ("chuang.fan@chiachang.com", "生管"),
    ("mingxing.wang@chiachang.com", "生管"), ("linfan.zhang@chiachang.com", "制造二部经理"),
    ("b-mfg210@chiachang.com", "制二统计"), ("yaya.fan@chiachang.com", "制一统计"),
    ("l.c.cheng@chiachang.com", "总经理"),
]

today_str = datetime.now().strftime("%Y年%m月%d日")

# Read latest daily CSV
daily_files = sorted(DAILY_DIR.glob("V_PLAN_ACTUAL_SUMMARY_*.csv"), reverse=True)
df = pd.read_csv(daily_files[0], encoding='gbk')
df['PLANQTY'] = pd.to_numeric(df['PLANQTY'], errors='coerce').fillna(0).astype(int)
df['AUTOQTY'] = pd.to_numeric(df['AUTOQTY'], errors='coerce').fillna(0).astype(int)
df['NOTE'] = df['NOTE'].fillna('').str.strip()
df_norm = df[df['NOTE'] == '正常'].copy()

# Overall
total_plan = int(df_norm['PLANQTY'].sum())
total_actual = int(df_norm['AUTOQTY'].sum())
total_ach = total_actual / total_plan * 100 if total_plan else 0

# By dept+shift
d1 = df_norm[df_norm['LINE_ID'].str.match(r'^(NA|NB)')]
d2 = df_norm[df_norm['LINE_ID'].str.match(r'^NQ')]

for label, data in [('d1', d1), ('d2', d2)]:
    for shift in ['白班', '夜班']:
        sub = data[data['CLAS_TYPE'] == shift]
        globals()[f'{label}_{shift}_plan'] = int(sub['PLANQTY'].sum())
        globals()[f'{label}_{shift}_act'] = int(sub['AUTOQTY'].sum())

# Line ranking
line_ach = df_norm.groupby('LINE_ID').agg(
    plan=('PLANQTY','sum'), actual=('AUTOQTY','sum'),
    model=('ACTUAL_MODEL_LIST', lambda x: '/'.join(sorted(set(str(m) for m in x if str(m).strip()))[:40]))
).reset_index()
line_ach['ach'] = (line_ach['actual'] / line_ach['plan'].replace(0,1) * 100).clip(0,200)
line_ach = line_ach[line_ach['plan'] > 0].sort_values('ach', ascending=False)

d1_lines = line_ach[line_ach['LINE_ID'].str.match(r'^(NA|NB)')]
d2_lines = line_ach[line_ach['LINE_ID'].str.match(r'^NQ')]

def fmt_top(items, n=3):
    lines = []
    for _, r in items.head(n).iterrows():
        lines.append(f"    {r['LINE_ID']} | {str(r['model'])[:20]} | 计划{int(r['plan']):,} 实际{int(r['actual']):,} 达成率{r['ach']:.1f}%")
    return '\n'.join(lines)

# Build email
body = f"""各位主管，{'早上' if datetime.now().hour < 12 else '晚上'}好：

{today_str} 生产日报已生成。

═══════════════════════════════
  📊 关键指标
═══════════════════════════════
  全厂: 计划 {total_plan:,} / 实际 {total_actual:,} / 达成率 {total_ach:.1f}%

  🏭 制造一部（冲压）
    夜班 计划 {d1_夜班_plan:,} 实际 {d1_夜班_act:,}
    白班 计划 {d1_白班_plan:,} 实际 {d1_白班_act:,}

  🏗️ 制造二部（清洗+组装）
    夜班 计划 {d2_夜班_plan:,} 实际 {d2_夜班_act:,}
    白班 计划 {d2_白班_plan:,} 实际 {d2_白班_act:,}
═══════════════════════════════

【📝 关注产线】
  低达成率产线：
{fmt_top(d1_lines.tail(3), 3)}
{fmt_top(d2_lines.tail(3), 3)}

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

【🌗 同机种日夜班差异 TOP 5】
  使用当前日报 HTML 查看：{REPORT_URL_BASE}/

📎 完整日报：{REPORT_URL_BASE}/{sorted(OUTPUT_DIR.glob('生产日报_*.html'), reverse=True)[0].name if list(OUTPUT_DIR.glob('生产日报_*.html')) else ''}

此致 · MES系统自动发送
"""

# Send
msg = MIMEMultipart()
msg['From'] = f"{SENDER_NAME} <{SENDER}>"
msg['To'] = ', '.join(a for a,_ in RECIPIENTS)
msg['Subject'] = Header(f"[测试]生产日报 - {datetime.now().strftime('%m/%d')}", 'utf-8')
msg.attach(MIMEText(body, 'plain', 'utf-8'))

server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
server.login(SMTP_USER, SMTP_PASS)
server.sendmail(SENDER, [a for a,_ in RECIPIENTS], msg.as_string())
server.quit()
print("✅ 已发送")

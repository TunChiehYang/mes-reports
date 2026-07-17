#!/usr/bin/env python3
"""7天每日出货缺口 — 以清洗产能为瓶颈，按比例分配缺口到机种"""
import pandas as pd, re
from datetime import datetime, timedelta
from pathlib import Path

PLAN_DIR = Path("/mnt/d/ShareExport/output/V_MONTH_PLAN")
DAILY_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
STOCK_DIR = Path("/mnt/d/ShareExport/output/daily_stock")
OUT = Path("/mnt/d/outputHTML")

today = pd.Timestamp(datetime.now().strftime('%Y-%m-%d'))

plan_files = sorted(PLAN_DIR.glob("V_MONTH_PLAN_*.csv"), reverse=True)
daily_files = sorted(DAILY_DIR.glob("V_PLAN_ACTUAL_SUMMARY_*.csv"), reverse=True)
stock_files = sorted(STOCK_DIR.glob("stock*.xlsx"), reverse=True)

if not plan_files: print("no plan"); exit(1)
if not daily_files: print("no daily"); exit(1)

plan_file = plan_files[0]; daily_file = daily_files[0]
stock_file = stock_files[0] if stock_files else None
print(f"计划:{plan_file.name} 日报:{daily_file.name}")

# Load
df_plan = pd.read_csv(plan_file, encoding='utf-8-sig')
df_plan.columns = [c.strip().strip('"') for c in df_plan.columns]
df_plan['RUNCARD_QTY'] = pd.to_numeric(df_plan['RUNCARD_QTY'], errors='coerce').fillna(0).astype(int)
df_plan['YMD_DATE'] = pd.to_datetime(df_plan['YMD'], format='%Y/%m/%d', errors='coerce')
df7 = df_plan[(df_plan['YMD_DATE'] >= today) & (df_plan['YMD_DATE'] < today + pd.Timedelta(days=7))].copy()

stock_by_model = {}
if stock_file:
    df_stock = pd.read_excel(stock_file, header=None, skiprows=1)
    df_stock.columns = ['pn','md','sp','wh','loc','bt','qty','un','nt']
    df_stock['qty'] = pd.to_numeric(df_stock['qty'], errors='coerce').fillna(0).astype(int)
    stock_by_model = df_stock.groupby('md')['qty'].sum().to_dict()

df_daily = pd.read_csv(daily_file, encoding='gbk')
df_daily['PLANQTY'] = pd.to_numeric(df_daily['PLANQTY'], errors='coerce').fillna(0).astype(int)
df_daily['AUTOQTY'] = pd.to_numeric(df_daily['AUTOQTY'], errors='coerce').fillna(0).astype(int)
df_norm = df_daily[df_daily['NOTE'].str.strip() == '正常'].copy()

# Delivery bottleneck = 制造二部(NQ) capacity
dept1_cap = int(df_norm[df_norm['LINE_ID'].str.match(r'^(NA|NB)')]['AUTOQTY'].sum())
dept2_cap = int(df_norm[df_norm['LINE_ID'].str.match(r'^NQ')]['AUTOQTY'].sum())
delivery_cap = dept2_cap

model_lines = df7.groupby('MODEL_NO')['LINE_ID'].apply(lambda x: list(set(x))).to_dict()
daily_plan = df7.groupby(['YMD_DATE','MODEL_NO'])['RUNCARD_QTY'].sum().reset_index()
daily_plan.columns = ['date','model','plan_qty']
dates_list = sorted(daily_plan['date'].unique())

# ====== CORRECTED GAP LOGIC ======
# Step 1: Per model per day, calculate net need = plan - stock
gap_matrix = {}
for _, row in daily_plan.iterrows():
    model = row['model']; date = row['date']; plan = int(row['plan_qty'])
    stock = stock_by_model.get(model, 0)
    need = max(0, plan - stock)
    
    if model not in gap_matrix: gap_matrix[model] = {}
    gap_matrix[model][date] = {'plan':plan, 'stock':stock, 'need':need, 'gap':0}

# Step 2: Per day, sum all net needs, compare to delivery_cap
for date in dates_list:
    total_need_day = sum(gap_matrix[m][date]['need'] for m in gap_matrix if date in gap_matrix[m])
    overshoot = total_need_day - delivery_cap
    
    if overshoot > 0:
        # Prorate gap to models proportionally
        for model in gap_matrix:
            if date in gap_matrix[model] and gap_matrix[model][date]['need'] > 0:
                share = gap_matrix[model][date]['need'] / total_need_day
                gap_matrix[model][date]['gap'] = int(share * overshoot)

# Step 3: Model totals
model_total_gap = {}
for model, dates in gap_matrix.items():
    model_total_gap[model] = sum(max(0, d['gap']) for d in dates.values())
    # Add lines info
    lines = model_lines.get(model, [])
    gap_matrix[model]['__lines'] = ','.join(lines[:3])

gap_models = [(m,g) for m,g in sorted(model_total_gap.items(), key=lambda x:x[1], reverse=True) if g>0]

daily_gap_sum = {}; day_all_gap = 0
for d in dates_list:
    dg = sum(max(0, gap_matrix.get(m,{}).get(d,{}).get('gap',0)) for m,_ in gap_models)
    daily_gap_sum[d] = dg; day_all_gap += dg

now = datetime.now()
date_labels = [d.strftime('%m/%d') for d in dates_list]

rows_html = ""
for model, total_gap in gap_models[:60]:
    info = gap_matrix[model]
    lines = info.get('__lines', ''); stock = 0
    for d in dates_list:
        if d in info: stock = info[d]['stock']; break
    
    row = "<tr><td>" + model[:38] + "</td><td style='font-size:11px'>" + lines + "</td><td class='n'>" + f"{stock:,}" + "</td>"
    total_need = 0
    for d in dates_list:
        di = info.get(d, {'plan':0,'need':0,'gap':0})
        total_need += di['need']
        if di['gap'] > 0: row += "<td class='n' style='background:#ffeaea;color:#e74c3c;font-weight:600'>" + f"{di['gap']:,}" + "</td>"
        elif di['need'] > 0: row += "<td class='n' style='background:#e8f8f5;color:#27ae60'>OK</td>"
        else: row += "<td class='n' style='color:#ccc'>—</td>"
    row += "<td class='n' style='font-weight:700'>" + f"{total_need:,}" + "</td>"
    row += "<td class='n' style='color:#e74c3c;font-weight:700'>" + f"{total_gap:,}" + "</td></tr>"
    rows_html += row

sum_cells = ""
for d in dates_list: sum_cells += "<td class='n' style='color:#e74c3c'>" + f"{daily_gap_sum.get(d,0):,}" + "</td>"
sum_row = "<tr style='background:#f0f4f8;font-weight:700'><td colspan='3'>每日出货缺口合计</td>" + sum_cells + "<td class='n'></td><td class='n' style='color:#e74c3c'>" + f"{day_all_gap:,}" + "</td></tr>"

html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>7天出货缺口推估</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;-webkit-user-select:text;user-select:text}
.c{max-width:1700px;margin:0 auto}
.hd{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:16px 24px;border-radius:14px;margin-bottom:14px}
.hd h1{font-size:20px}.hd .m{font-size:12px;opacity:.8;margin-top:4px}
.kr{display:flex;gap:10px;margin-bottom:14px}
.kc{flex:1;background:#fff;border-radius:10px;padding:10px 14px;box-shadow:0 2px 6px rgba(0,0,0,.05);text-align:center}
.kc .l{font-size:11px;color:#888}.kc .v{font-size:20px;font-weight:700}
.sec{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 2px 6px rgba(0,0,0,.05);margin-bottom:14px}
.sec h2{font-size:15px;color:#1a1a2e;margin-bottom:8px;padding-bottom:4px;border-bottom:2px solid #3498db}
table{width:100%;border-collapse:collapse;font-size:11px}
th{background:#f8f9fa;padding:5px 7px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6;position:sticky;top:0;z-index:1}
td{padding:4px 7px;border-bottom:1px solid #f1f3f5}
tr:hover td{background:#f8f9ff}.n{text-align:right}
.tw{max-height:750px;overflow-y:auto}
.legend{display:flex;gap:16px;margin-bottom:10px;font-size:12px}
.legend span{display:flex;align-items:center;gap:4px}
.leg-gap{width:16px;height:16px;background:#ffeaea;border:1px solid #e74c3c;border-radius:3px}
.leg-ok{width:16px;height:16px;background:#e8f8f5;border:1px solid #27ae60;border-radius:3px}
.note{background:#fff3cd;border-left:4px solid #f39c12;padding:10px 14px;border-radius:6px;font-size:13px;margin-bottom:14px}
</style></head><body><div class="c">
<div class="hd"><h1>7天出货缺口推估（成品入库·按比例分配）</h1><div class="m">"""
html += f"冲压→半成品→清洗组装→成品入库 | 出货瓶颈(清洗):{dept2_cap:,}/日 | 缺口=当日总需求超清洗产能时按需比例分配 | 生成:{now.strftime('%H:%M')}</div></div>"
html += f"""<div class="note">📌 <b>算法：</b>每日汇总所有机种净需求(计划−库存)，超出清洗日产能({dept2_cap:,})部分按各机种需求比例分配缺口。</div>
<div class="kr">
<div class="kc"><div class="l">7天计划</div><div class="v" style="color:#3498db">{int(df7['RUNCARD_QTY'].sum())/10000:.1f}万</div></div>
<div class="kc"><div class="l">仓库库存</div><div class="v" style="color:#2ecc71">{sum(stock_by_model.values())/10000:.1f}万</div></div>
<div class="kc"><div class="l">冲压日产能</div><div class="v" style="color:#2e86c1">{dept1_cap/10000:.1f}万</div></div>
<div class="kc"><div class="l">清洗日产能(瓶颈)</div><div class="v" style="color:#27ae60">{dept2_cap/10000:.1f}万</div></div>
<div class="kc"><div class="l">出货缺口</div><div class="v" style="color:#c0392b">{day_all_gap/10000:.1f}万</div></div>
</div>
<div class="legend"><span><div class="leg-gap"></div>产能不足</span><span><div class="leg-ok"></div>可满足</span></div>
<div class="sec"><h2>机种 × 日期 出货缺口矩阵（TOP 60）</h2>
<div class="tw"><table><thead><tr><th>机种</th><th>产线</th><th>库存</th>"""
for l in date_labels: html += f"<th class='n'>{l}</th>"
html += "<th class='n'>净需求</th><th class='n'>出货缺口</th></tr></thead><tbody>" + rows_html + sum_row + "</tbody></table></div></div>"
html += "</div></body></html>"

nm = "每日缺口推估_" + now.strftime('%Y%m%d_%H%M') + ".html"
op = OUT / nm; op.parent.mkdir(parents=True, exist_ok=True)
op.write_text(html, encoding='utf-8')
print(f"OK {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{nm}")
print(f"清洗瓶颈:{dept2_cap:,}/日 | 冲压:{dept1_cap:,}/日 | 缺口:{day_all_gap:,} | {len(gap_models)}机种")
import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])

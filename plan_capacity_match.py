#!/usr/bin/env python3
"""7天计划 vs 日产能 匹配分析 — 识别无法满足交期的机种"""
import pandas as pd, re, io, base64
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

for f in ['WenQuanYi Zen Hei']:
    if f in {x.name for x in fm.fontManager.ttflist}: plt.rcParams['font.family']=f; break
plt.rcParams['axes.unicode_minus'] = False

PLAN_FILE = Path("/mnt/d/ShareExport/output/V_MONTH_PLAN/V_MONTH_PLAN_20260714_162015.csv")
DAILY_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
OUT = Path("/mnt/d/outputHTML")

def get_dept(line):
    line=str(line).strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$',line): return ("制造一部","冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$',line): return ("制造一部","冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$',line): return ("制造一部","冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$',line): return ("制造二部","清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$',line): return ("制造二部","清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$',line): return ("制造二部","清洗三课")
    return ("未分类","未分类")

# ====== 1. Load plan ======
df_plan = pd.read_csv(PLAN_FILE, encoding='utf-8-sig')
df_plan.columns = [c.strip().strip('"') for c in df_plan.columns]
df_plan['RUNCARD_QTY'] = pd.to_numeric(df_plan['RUNCARD_QTY'], errors='coerce').fillna(0).astype(int)
df_plan['YMD_DATE'] = pd.to_datetime(df_plan['YMD'], format='%Y/%m/%d', errors='coerce')
today = pd.Timestamp('2026-07-14')
df7 = df_plan[(df_plan['YMD_DATE'] >= today) & (df_plan['YMD_DATE'] < today + pd.Timedelta(days=7))].copy()
print(f"7天计划: {len(df7)}条, {df7['RUNCARD_QTY'].sum():,}pcs")

# Plan by model
model_plan = df7.groupby('MODEL_NO').agg(
    total=('RUNCARD_QTY','sum'), lines=('LINE_ID', lambda x: ','.join(sorted(set(x)))),
    earliest=('YMD_DATE','min'), latest=('YMD_DATE','max')
).reset_index()
model_plan = model_plan.sort_values('total', ascending=False)

# ====== 2. Load daily capacity ======
# Find latest daily report
daily_files = sorted(DAILY_DIR.glob("V_PLAN_ACTUAL_SUMMARY_*.csv"), reverse=True)
latest_daily = daily_files[0]
print(f"日报: {latest_daily.name}")

df_daily = pd.read_csv(latest_daily, encoding='gbk')
df_daily['PLANQTY'] = pd.to_numeric(df_daily['PLANQTY'], errors='coerce').fillna(0).astype(int)
df_daily['AUTOQTY'] = pd.to_numeric(df_daily['AUTOQTY'], errors='coerce').fillna(0).astype(int)
df_daily['NOTE'] = df_daily['NOTE'].fillna('').str.strip()
df_norm = df_daily[df_daily['NOTE'] == '正常'].copy()

# Daily capacity by line
line_capacity = df_norm.groupby('LINE_ID').agg(
    plan=('PLANQTY','sum'), actual=('AUTOQTY','sum')
).reset_index()
line_capacity['day_ach'] = (line_capacity['actual'] / line_capacity['plan'].replace(0,1) * 100).clip(0,200)
print(f"正常产线: {len(line_capacity)}条, 日均产能: {line_capacity['actual'].sum():,}pcs")

# ====== 3. Match: plan vs capacity ======
# For each model in the plan, estimate daily capacity from its lines
model_analysis = []
for _, mp in model_plan.iterrows():
    model = mp['MODEL_NO']
    plan_lines = [l.strip() for l in mp['lines'].split(',')]
    
    # Get capacity for these lines
    line_caps = line_capacity[line_capacity['LINE_ID'].isin(plan_lines)]
    daily_cap = int(line_caps['actual'].sum()) if len(line_caps) > 0 else 0
    
    # Days available
    days_avail = max(1, (mp['latest'] - mp['earliest']).days + 1)
    cap_in_period = daily_cap * days_avail
    
    gap = mp['total'] - cap_in_period
    gap_pct = gap / mp['total'] * 100 if mp['total'] else 0
    
    model_analysis.append({
        'model': model[:50], 'plan_qty': int(mp['total']), 'lines': mp['lines'],
        'daily_cap': daily_cap, 'days': days_avail, 'cap_in_period': cap_in_period,
        'gap': gap, 'gap_pct': gap_pct,
        'earliest': mp['earliest'].strftime('%m/%d'), 'latest': mp['latest'].strftime('%m/%d'),
    })

# Sort by gap descending (biggest shortfall first)
model_analysis.sort(key=lambda x: x['gap'], reverse=True)
risk_models = [m for m in model_analysis if m['gap'] > 0]
print(f"有缺口机种: {len(risk_models)}/{len(model_analysis)}")

# ====== 4. Charts ======
def fig2b64(fig):
    b=io.BytesIO(); fig.savefig(b,format='png',dpi=130,bbox_inches='tight',facecolor='white')
    b.seek(0); r=base64.b64encode(b.read()).decode(); plt.close(fig); return r

# Chart 1: Top 15 risk models
top_risk = risk_models[:15]
fig1,ax1=plt.subplots(figsize=(12,6))
lbls=[m['model'][:30] for m in top_risk]; gv=[m['gap']/10000 for m in top_risk]
cv=[m['cap_in_period']/10000 for m in top_risk]; pv=[m['plan_qty']/10000 for m in top_risk]
x=np.arange(len(lbls)); w=0.35
ax1.barh(x+w/2, pv, w, label='7天计划(万)', color='#3498db', alpha=0.85)
ax1.barh(x-w/2, cv, w, label='推算产能(万)', color='#e74c3c', alpha=0.85)
for i,(g,p) in enumerate(zip(gv,pv)):
    if g>0: ax1.text(p+0.3, i, f'缺口{g:.1f}万', va='center', fontsize=8, color='#e74c3c', fontweight='bold')
ax1.set_yticks(x); ax1.set_yticklabels(lbls, fontsize=9)
ax1.set_title('产能缺口 TOP 15 机种（7天计划 vs 推算产能）', fontweight='bold')
ax1.legend(fontsize=9, loc='lower right'); ax1.grid(axis='x',alpha=.3); ax1.invert_yaxis()
fig1.tight_layout(); chart1=fig2b64(fig1)

# Chart 2: Gap distribution
fig2,ax2=plt.subplots(figsize=(8,5))
bins=[-100,-50,-20,-10,0,10,20,50,100,999]
labels=['充足>100%','充足50~100%','充足20~50%','充足0~20%','缺口0~10%','缺口10~20%','缺口20~50%','缺口50~100%','缺口>100%']
counts=[0]*len(labels)
for m in model_analysis:
    pct = -m['gap_pct'] if m['gap'] < 0 else m['gap_pct']
    if pct <= -100: counts[0]+=1
    elif pct <= -50: counts[1]+=1
    elif pct <= -20: counts[2]+=1
    elif pct <= 0: counts[3]+=1
    elif pct <= 10: counts[4]+=1
    elif pct <= 20: counts[5]+=1
    elif pct <= 50: counts[6]+=1
    elif pct <= 100: counts[7]+=1
    else: counts[8]+=1
colors2=['#27ae60','#2ecc71','#58d68d','#82e0aa','#f9e79f','#f5b041','#e74c3c','#c0392b','#922b21']
ax2.pie([c for c in counts if c>0], labels=[l for l,c in zip(labels,counts) if c>0], 
        colors=[c for l,c in zip(labels,colors2) if counts[labels.index(l)]>0], autopct='%1.1f%%', startangle=90)
ax2.set_title('机种产能匹配分布', fontweight='bold')
fig2.tight_layout(); chart2=fig2b64(fig2)

# ====== 5. HTML ======
# Risk table
risk_rows=""
for m in risk_models[:20]:
    c='#c0392b' if m['gap_pct']>50 else '#e74c3c' if m['gap_pct']>20 else '#f39c12'
    risk_rows+=f"<tr><td>{m['model']}</td><td>{m['lines']}</td><td>{m['earliest']}~{m['latest']}</td><td class='n'>{m['plan_qty']:,}</td><td class='n'>{m['daily_cap']:,}</td><td class='n'>{m['cap_in_period']:,}</td><td class='n' style='color:{c};font-weight:700'>{'+' if m['gap']<0 else ''}{m['gap']:,}</td><td class='a' style='color:{c}'>{m['gap_pct']:.0f}%</td></tr>"

now=datetime.now()
html=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>7天计划产能匹配分析</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;-webkit-user-select:text;user-select:text}}
.c{{max-width:1300px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:20px 28px;border-radius:14px;margin-bottom:18px}}
.hd h1{{font-size:21px}}.hd .m{{font-size:12px;opacity:.8;margin-top:4px}}
.kr{{display:flex;gap:10px;margin-bottom:16px}}
.kc{{flex:1;background:#fff;border-radius:10px;padding:12px 16px;box-shadow:0 2px 6px rgba(0,0,0,.05);text-align:center}}
.kc .l{{font-size:11px;color:#888}}.kc .v{{font-size:22px;font-weight:700}}.kc .s{{font-size:10px;color:#aaa}}
.sc{{background:#fff;border-radius:10px;padding:16px 20px;margin-bottom:14px;box-shadow:0 2px 6px rgba(0,0,0,.05)}}
.sc h2{{font-size:15px;color:#1a1a2e;margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid #3498db}}
img{{max-width:100%;border-radius:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f8f9fa;padding:7px 10px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6}}
td{{padding:6px 10px;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9ff}}.n{{text-align:right}}.a{{text-align:right;font-weight:600}}
.gr{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.tw{{max-height:500px;overflow-y:auto}}
@media(max-width:900px){{.gr{{grid-template-columns:1fr}}.kr{{flex-wrap:wrap}}}}
</style></head><body><div class="c">
<div class="hd"><h1>7天计划 vs 日产能 匹配分析</h1><div class="m">计划: {today.strftime('%m/%d')}~{(today+timedelta(days=6)).strftime('%m/%d')} | {len(df7)}条 | {df7['MODEL_NO'].nunique()}机种 | 日报参考: {latest_daily.name} | 生成:{now.strftime('%H:%M')}</div></div>

<div class="kr">
<div class="kc"><div class="l">7天计划总量</div><div class="v" style="color:#3498db">{df7['RUNCARD_QTY'].sum()/10000:.1f}万</div><div class="s">pcs</div></div>
<div class="kc"><div class="l">机种数</div><div class="v" style="color:#9b59b6">{df7['MODEL_NO'].nunique()}</div><div class="s">个</div></div>
<div class="kc"><div class="l">产能不足机种</div><div class="v" style="color:#e74c3c">{len(risk_models)}</div><div class="s">/{len(model_analysis)} 有缺口</div></div>
<div class="kc"><div class="l">缺口总量</div><div class="v" style="color:#c0392b">{sum(m['gap'] for m in risk_models)/10000:.1f}万</div><div class="s">pcs</div></div>
</div>

<div class="sc"><h2>产能缺口 TOP 15 机种</h2><img src="data:image/png;base64,{chart1}"></div>
<div class="gr">
<div class="sc"><h2>产能匹配分布</h2><img src="data:image/png;base64,{chart2}"></div>
<div class="sc"><h2>缺口机种明细 TOP 20</h2><div class="tw"><table><thead><tr><th>机种</th><th>产线</th><th>交期</th><th>7天计划</th><th>日产能</th><th>推算产能</th><th>缺口</th><th>缺口%</th></tr></thead><tbody>{risk_rows}</tbody></table></div></div>
</div>

</div></body></html>"""

nm=f"计划产能匹配_{now.strftime('%Y%m%d_%H%M')}.html"
op=OUT/nm; op.parent.mkdir(parents=True,exist_ok=True); op.write_text(html,encoding='utf-8')
print(f"✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{nm}")
import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])

#!/usr/bin/env python3
"""每日早会报告 — 汇总当班分析、异常工时、出货缺口、生产日报"""
import pandas as pd, re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import io, base64

for f in ['WenQuanYi Zen Hei']:
    if f in {x.name for x in fm.fontManager.ttflist}: plt.rcParams['font.family']=f; break
plt.rcParams['axes.unicode_minus'] = False

PLAN_DIR = Path("/mnt/d/ShareExport/output/V_MONTH_PLAN")
DAILY_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
STOCK_DIR = Path("/mnt/d/ShareExport/output/daily_stock")
EXCEPTION_DIR = Path("/mnt/d/ShareExport/output/V_R_EXCEPTION_HOUR_DETAIL")
OUT = Path("/mnt/d/outputHTML")

today = pd.Timestamp(datetime.now().strftime('%Y-%m-%d'))

def get_dept(line):
    line=str(line).strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$',line): return ("制造一部","冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$',line): return ("制造一部","冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$',line): return ("制造一部","冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$',line): return ("制造二部","清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$',line): return ("制造二部","清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$',line): return ("制造二部","清洗三课")
    return ("未分类","未分类")

def fig2b64(fig):
    b=io.BytesIO(); fig.savefig(b,format='png',dpi=120,bbox_inches='tight',facecolor='white')
    b.seek(0); r=base64.b64encode(b.read()).decode(); plt.close(fig); return r

# ====== 1. 生产日报 KPI ======
daily_files = sorted(DAILY_DIR.glob("V_PLAN_ACTUAL_SUMMARY_*.csv"), reverse=True)
daily_file = daily_files[0]
df_daily = pd.read_csv(daily_file, encoding='gbk')
df_daily['PLANQTY'] = pd.to_numeric(df_daily['PLANQTY'], errors='coerce').fillna(0).astype(int)
df_daily['AUTOQTY'] = pd.to_numeric(df_daily['AUTOQTY'], errors='coerce').fillna(0).astype(int)
df_norm = df_daily[df_daily['NOTE'].str.strip() == '正常'].copy()
daily_total_plan = int(df_norm['PLANQTY'].sum())
daily_total_actual = int(df_norm['AUTOQTY'].sum())
daily_ach = daily_total_actual / daily_total_plan * 100 if daily_total_plan else 0
daily_lines = df_norm['LINE_ID'].nunique()

# Dept split
d1 = df_norm[df_norm['LINE_ID'].str.match(r'^(NA|NB)')]
d2 = df_norm[df_norm['LINE_ID'].str.match(r'^NQ')]
d1_plan, d1_act = int(d1['PLANQTY'].sum()), int(d1['AUTOQTY'].sum())
d2_plan, d2_act = int(d2['PLANQTY'].sum()), int(d2['AUTOQTY'].sum())
d1_ach = d1_act / d1_plan * 100 if d1_plan else 0
d2_ach = d2_act / d2_plan * 100 if d2_plan else 0

# ====== 2. 出货缺口 ======
plan_files = sorted(PLAN_DIR.glob("V_MONTH_PLAN_*.csv"), reverse=True)
stock_files = sorted(STOCK_DIR.glob("stock*.xlsx"), reverse=True)
plan_file = plan_files[0]; stock_file = stock_files[0] if stock_files else None

df_plan = pd.read_csv(plan_file, encoding='utf-8-sig')
df_plan.columns = [c.strip().strip('"') for c in df_plan.columns]
df_plan['RUNCARD_QTY'] = pd.to_numeric(df_plan['RUNCARD_QTY'], errors='coerce').fillna(0).astype(int)
df_plan['YMD_DATE'] = pd.to_datetime(df_plan['YMD'], format='%Y/%m/%d', errors='coerce')
df7 = df_plan[(df_plan['YMD_DATE'] >= today) & (df_plan['YMD_DATE'] < today + pd.Timedelta(days=7))]

stock_by_model = {}
if stock_file:
    df_stock = pd.read_excel(stock_file, header=None, skiprows=1)
    df_stock.columns = ['pn','md','sp','wh','loc','bt','qty','un','nt']
    df_stock['qty'] = pd.to_numeric(df_stock['qty'], errors='coerce').fillna(0).astype(int)
    stock_by_model = df_stock.groupby('md')['qty'].sum().to_dict()

line_cap = df_norm.groupby('LINE_ID')['AUTOQTY'].sum().to_dict()
model_lines = df7.groupby('MODEL_NO')['LINE_ID'].apply(lambda x: list(set(x))).to_dict()
daily_plan = df7.groupby(['YMD_DATE','MODEL_NO'])['RUNCARD_QTY'].sum().reset_index()
daily_plan.columns = ['date','model','plan_qty']

gap_total = 0; gap_count = 0
for _, row in daily_plan.iterrows():
    model = row['model']; plan = int(row['plan_qty'])
    lines = model_lines.get(model, [])
    cap = sum(line_cap.get(l, 0) for l in lines)
    stock = stock_by_model.get(model, 0)
    need = max(0, plan - stock)
    gap = need - cap
    if gap > 0: gap_total += gap; gap_count += 1

plan7_total = int(df7['RUNCARD_QTY'].sum())
stock_total = sum(stock_by_model.values())

# ====== 3. 异常工时 ======
exc_files = sorted(EXCEPTION_DIR.glob("V_R_EXCEPTION_HOUR_DETAIL_*.csv"), reverse=True)
exception_data = None
if exc_files:
    df_exc = pd.read_csv(exc_files[0], encoding='gbk')
    df_exc['TOTAL_CE_TIME'] = pd.to_numeric(df_exc['TOTAL_CE_TIME'], errors='coerce').fillna(0).astype(int)
    
    # Filter to 制造一部
    df_exc['IS_D1'] = df_exc['USER_NO'].str.match(r'^(NA|NB)')
    df_exc_d1 = df_exc[df_exc['IS_D1']]
    
    # Parse time breakdown
    planned_cats = ['其他计划停线','计划停机','管理时间']
    def parse_exc(desc):
        result = {}
        for part in str(desc).replace('\\n','\n').split('\n'):
            for item in part.split(','):
                item=item.strip()
                if ':' in item:
                    k,v = item.split(':',1)
                    try: result[k.strip()]=int(v.strip())
                    except: pass
        return result
    
    exc_total = int(df_exc_d1['TOTAL_CE_TIME'].sum())
    exc_prod = 0; exc_unplanned = 0; exc_cats = defaultdict(int)
    for _, r in df_exc_d1.iterrows():
        bd = parse_exc(r['DESC_CE_LIST'])
        for k,v in bd.items():
            if k == '生产': exc_prod += v
            elif k not in planned_cats: exc_unplanned += v; exc_cats[k] += v
    
    exc_ach = exc_prod / exc_total * 100 if exc_total else 0
    exc_unp_pct = exc_unplanned / exc_total * 100 if exc_total else 0
    top_exc = sorted(exc_cats.items(), key=lambda x:x[1], reverse=True)[:3]
    exception_data = {'total':exc_total,'prod':exc_prod,'unplanned':exc_unplanned,
                      'ach':exc_ach,'unp_pct':exc_unp_pct,'top3':top_exc,'file':exc_files[0].name}

# ====== Chart: Daily KPI bars ======
fig1,ax1=plt.subplots(figsize=(8,4))
dept_labels=['制造一部','制造二部']
plan_vals=[d1_plan/10000, d2_plan/10000]
act_vals=[d1_act/10000, d2_act/10000]
ach_vals=[d1_ach, d2_ach]
x=np.arange(2); w=0.3
ax1.bar(x-w/2, plan_vals, w, label='计划(万)', color='#3498db', alpha=0.85)
ax1.bar(x+w/2, act_vals, w, label='实际(万)', color='#27ae60', alpha=0.85)
for i,(a,p) in enumerate(zip(ach_vals,act_vals)):
    ax1.text(i, p+0.5, f'{a:.1f}%', ha='center', fontweight='bold', fontsize=12, color='#e74c3c' if a<50 else '#27ae60')
ax1.set_xticks(x); ax1.set_xticklabels(dept_labels, fontsize=12)
ax1.set_title('本日生产达成', fontweight='bold'); ax1.legend(fontsize=9); ax1.grid(axis='y',alpha=.3)
fig1.tight_layout(); chart1=fig2b64(fig1)

# ====== HTML ======
now=datetime.now()
exc_html=""
if exception_data:
    e=exception_data
    top3_str = '、'.join(f'{k}({v/60:.0f}h)' for k,v in e['top3'])
    exc_html=f"""<div class="kr">
<div class="kc" style="border-left:4px solid #e74c3c"><div class="l">制造一部异常停机率</div><div class="v" style="color:#e74c3c">{e['unp_pct']:.1f}%</div><div class="s">{e['unplanned']/60:.0f}h / {e['total']/60:.0f}h</div></div>
<div class="kc"><div class="l">有效生产</div><div class="v" style="color:#27ae60">{e['ach']:.1f}%</div><div class="s">{e['prod']/60:.0f}h</div></div>
<div class="kc"><div class="l">TOP3 异常</div><div class="v" style="color:#c0392b;font-size:16px">{top3_str}</div><div class="s">数据:{e['file'][:30]}</div></div>
</div>"""
else:
    exc_html="""<div class="kr"><div class="kc"><div class="l">异常工时</div><div class="v" style="color:#aaa">暂无数据</div></div></div>"""

html=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>每日早会报告 - {today.strftime('%m/%d')}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:16px;-webkit-user-select:text;user-select:text}}
.c{{max-width:1200px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:20px 28px;border-radius:14px;margin-bottom:16px;text-align:center}}
.hd h1{{font-size:24px}}.hd .m{{font-size:13px;opacity:.8;margin-top:4px}}
.sec{{background:#fff;border-radius:12px;padding:16px 20px;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.sec h2{{font-size:16px;color:#1a1a2e;margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid #3498db;display:flex;align-items:center;gap:8px}}
.sec h2 .icon{{font-size:22px}}
.kr{{display:flex;gap:10px;margin-bottom:12px}}
.kc{{flex:1;background:#f8f9fb;border-radius:10px;padding:12px 16px;text-align:center}}
.kc .l{{font-size:11px;color:#888}}.kc .v{{font-size:22px;font-weight:700;margin:2px 0}}.kc .s{{font-size:10px;color:#aaa}}
img{{max-width:100%;border-radius:6px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f8f9fa;padding:6px 8px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6}}
td{{padding:5px 8px;border-bottom:1px solid #f1f3f5}}
.n{{text-align:right}}.a{{text-align:right;font-weight:600;color:#e74c3c}}
.summary{{background:#fffbe6;border-left:4px solid #f39c12;padding:14px 18px;border-radius:8px;margin-bottom:14px;font-size:14px;line-height:1.8}}
</style></head><body><div class="c">
<div class="hd"><h1>📋 每日早会报告</h1><div class="m">{today.strftime('%Y年%m月%d日')} | 数据截止: {now.strftime('%H:%M')} | MES自动生成</div></div>

<div class="summary">📌 <b>今日要点：</b>生产日报达成率 <b>{daily_ach:.1f}%</b>（制造一部{d1_ach:.1f}%/制造二部{d2_ach:.1f}%）；7天出货缺口 <b>{gap_total/10000:.1f}万</b>（{gap_count}机种）；制造一部异常停机率 <b>{exc_unp_pct if exception_data else '—'}</b></div>

<div class="sec"><h2><span class="icon">📊</span> 生产日报 — 本日达成</h2>
<div class="kr">
<div class="kc" style="border-left:4px solid #3498db"><div class="l">全厂计划/实际</div><div class="v" style="color:#3498db">{daily_total_plan:,} / {daily_total_actual:,}</div><div class="s">{daily_lines}条线 | 达成率 {daily_ach:.1f}%</div></div>
<div class="kc" style="border-left:4px solid #27ae60"><div class="l">制造一部</div><div class="v" style="color:#27ae60">{d1_act:,}</div><div class="s">计划{d1_plan:,} | 达成率 {d1_ach:.1f}%</div></div>
<div class="kc" style="border-left:4px solid #f39c12"><div class="l">制造二部</div><div class="v" style="color:#f39c12">{d2_act:,}</div><div class="s">计划{d2_plan:,} | 达成率 {d2_ach:.1f}%</div></div>
</div>
<img src="data:image/png;base64,{chart1}" style="max-width:100%">
</div>

<div class="sec"><h2><span class="icon">📦</span> 出货缺口推估 — 7天展望</h2>
<div class="kr">
<div class="kc" style="border-left:4px solid #3498db"><div class="l">7天计划</div><div class="v" style="color:#3498db">{plan7_total/10000:.1f}万</div><div class="s">pcs</div></div>
<div class="kc" style="border-left:4px solid #2ecc71"><div class="l">仓库库存</div><div class="v" style="color:#2ecc71">{stock_total/10000:.1f}万</div><div class="s">pcs</div></div>
<div class="kc" style="border-left:4px solid #27ae60"><div class="l">日均产能</div><div class="v" style="color:#27ae60">{daily_total_actual/10000:.1f}万</div><div class="s">参考今日</div></div>
<div class="kc" style="border-left:4px solid #e74c3c"><div class="l">缺口机种</div><div class="v" style="color:#e74c3c">{gap_count}</div><div class="s">个</div></div>
<div class="kc" style="border-left:4px solid #c0392b"><div class="l">7天缺口</div><div class="v" style="color:#c0392b">{gap_total/10000:.1f}万</div><div class="s">pcs</div></div>
</div>
</div>

<div class="sec"><h2><span class="icon">⚠️</span> 异常工时 — 制造一部</h2>
{exc_html}
</div>

<div class="summary" style="text-align:center;color:#888;font-size:12px">
数据源: {daily_file.name} | {plan_file.name} | {stock_file.name if stock_file else '无'} | MES系统自动生成 {now.strftime('%H:%M')}
</div>
</div></body></html>"""

nm=f"早会报告_{now.strftime('%Y%m%d_%H%M')}.html"
op=OUT/nm; op.parent.mkdir(parents=True,exist_ok=True); op.write_text(html,encoding='utf-8')
print(f"✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{nm}")
import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])

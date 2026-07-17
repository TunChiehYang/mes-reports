#!/usr/bin/env python3
"""制造一部异常工时周分析 — 排除计划停机"""
import pandas as pd, re, io, base64
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

for f in ['WenQuanYi Zen Hei']:
    if f in {x.name for x in fm.fontManager.ttflist}: plt.rcParams['font.family']=f; break
plt.rcParams['axes.unicode_minus'] = False

SRC = Path("/mnt/d/ShareExport/output/V_R_EXCEPTION_HOUR_DETAIL/V_R_EXCEPTION_HOUR_DETAIL_20260702_105822.csv")
OUT = Path("/mnt/d/outputHTML")
PLANNED = ['其他计划停线', '计划停机', '管理时间']

df = pd.read_csv(SRC, encoding='gbk')
df['TOTAL_CE_TIME'] = pd.to_numeric(df['TOTAL_CE_TIME'], errors='coerce').fillna(0).astype(int)

# Parse date and week
def parse_date(s):
    s = str(s).strip()
    m = re.match(r'(\d{1,2})-(\d{1,2})月\s*-(\d{2})', s)
    if m: d, mo, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3)); return pd.Timestamp(y, mo, d)
    return pd.NaT

df['DT'] = df['WORK_DATE'].apply(parse_date)
df['WEEK'] = df['DT'].dt.isocalendar().week.astype(int)
df['MONTH'] = df['DT'].dt.month

def get_dept(line):
    line=str(line).strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$',line): return ("制造一部","冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$',line): return ("制造一部","冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$',line): return ("制造一部","冲压三课")
    if re.match(r'^NQ',line): return ("制造二部","")
    return ("未分类","未分类")

# Filter: 制造一部 only
df['DEPT'] = df['USER_NO'].apply(lambda x: get_dept(x)[0])
df = df[df['DEPT'] == '制造一部'].copy()
print(f"制造一部: {len(df)} 条记录")

# Parse breakdown, exclude planned
def parse_unplanned(desc):
    result = {}
    for part in str(desc).replace('\\n','\n').split('\n'):
        for item in part.split(','):
            item = item.strip()
            if ':' in item:
                k,v = item.split(':',1)
                try: result[k.strip()] = int(v.strip())
                except: pass
    return {k:v for k,v in result.items() if k not in PLANNED}

# Add breakdown to df
records = []
for _, r in df.iterrows():
    bd = parse_unplanned(r['DESC_CE_LIST'])
    prod = bd.pop('生产', 0)
    unplanned = sum(bd.values())
    records.append({
        'line': r['USER_NO'], 'week': r['WEEK'], 'shift': r['SHIFT'],
        'total': r['TOTAL_CE_TIME'], 'production': prod, 'unplanned': unplanned,
        'breakdown': bd, 'kes': get_dept(r['USER_NO'])[1],
        'model': str(r['MODEL_NOS']) if pd.notna(r['MODEL_NOS']) else '',
    })

# ====== Weekly Aggregation ======
weeks = sorted(set(r['week'] for r in records if pd.notna(r['week'])))

week_summary = []
for w in weeks:
    wr = [r for r in records if r['week'] == w]
    w_total = sum(r['total'] for r in wr)
    w_prod = sum(r['production'] for r in wr)
    w_unp = sum(r['unplanned'] for r in wr)
    
    # By kes within week
    kes_data = defaultdict(lambda: {'total':0,'prod':0,'unp':0})
    for r in wr:
        k = r['kes']; kes_data[k]['total'] += r['total']
        kes_data[k]['prod'] += r['production']; kes_data[k]['unp'] += r['unplanned']
    
    # Exception categories
    cat_data = defaultdict(int)
    for r in wr:
        for k,v in r['breakdown'].items(): cat_data[k] += v
    
    week_summary.append({
        'week': w, 'count': len(wr), 'total': w_total, 'prod': w_prod, 'unp': w_unp,
        'ach': w_prod/w_total*100 if w_total else 0, 'unp_pct': w_unp/w_total*100 if w_total else 0,
        'kes': dict(kes_data), 'cats': dict(cat_data),
    })

# Overall
total_t = sum(r['total'] for r in records)
total_p = sum(r['production'] for r in records)
total_u = sum(r['unplanned'] for r in records)

# Exception categories overall
all_cats = defaultdict(int)
for r in records:
    for k,v in r['breakdown'].items(): all_cats[k] += v

# Dept summary
dept_summary = defaultdict(lambda: {'total':0,'prod':0,'unp':0})
for r in records:
    k = r['kes']; dept_summary[k]['total'] += r['total']
    dept_summary[k]['prod'] += r['production']; dept_summary[k]['unp'] += r['unplanned']

# By line
line_summary = defaultdict(lambda: {'total':0,'prod':0,'unp':0})
for r in records:
    l = r['line']; line_summary[l]['total'] += r['total']
    line_summary[l]['prod'] += r['production']; line_summary[l]['unp'] += r['unplanned']

# By model (机种)
model_summary = defaultdict(lambda: {'total':0,'prod':0,'unp':0,'lines':set()})
for r in records:
    m = r['model'] if r['model'] else '(无机型)'
    model_summary[m]['total'] += r['total']
    model_summary[m]['prod'] += r['production']
    model_summary[m]['unp'] += r['unplanned']
    model_summary[m]['lines'].add(r['line'])

# ====== Charts ======
def fig2b64(fig):
    b=io.BytesIO(); fig.savefig(b,format='png',dpi=130,bbox_inches='tight',facecolor='white')
    b.seek(0); r=base64.b64encode(b.read()).decode(); plt.close(fig); return r

# Chart 1: Weekly trend
fig1,ax1=plt.subplots(figsize=(12,5))
wl=[f"W{w['week']}" for w in week_summary]
ax1.bar(np.arange(len(wl))-0.2, [w['prod']/60 for w in week_summary], 0.35, label='有效生产', color='#27ae60')
ax1.bar(np.arange(len(wl))+0.15, [w['unp']/60 for w in week_summary], 0.35, label='异常停机(排除计划)', color='#e74c3c')
for i,w in enumerate(week_summary):
    ax1.text(i, (w['prod']+w['unp'])/60+2, f"{w['unp_pct']:.0f}%", ha='center', fontsize=9, fontweight='bold', color='#e74c3c')
ax1.set_xticks(range(len(wl))); ax1.set_xticklabels(wl)
ax1.set_ylabel('工时(小时)'); ax1.set_title('制造一部 每周 生产 vs 异常停机(排除计划)', fontweight='bold')
ax1.legend(); ax1.grid(axis='y',alpha=.3)
fig1.tight_layout(); chart1=fig2b64(fig1)

# Chart 2: Categories TOP 10
fig2,ax2=plt.subplots(figsize=(8,6))
top_cats=sorted(all_cats.items(),key=lambda x:x[1],reverse=True)[:10]
lbs=[c[0] for c in top_cats]; vls=[c[1] for c in top_cats]
colors=plt.cm.tab10(np.linspace(0,1,len(lbs)))
w,_,_=ax2.pie(vls,labels=None,autopct='%1.1f%%',colors=colors,startangle=90)
ax2.set_title('异常类别 TOP 10(排除计划)',fontweight='bold')
ax2.legend(w,[f'{l} ({v/60:.0f}h)' for l,v in zip(lbs,vls)],loc='center left',bbox_to_anchor=(1,0.5),fontsize=9)
fig2.tight_layout(); chart2=fig2b64(fig2)

# Chart 3: Lines top 10
top_lines=sorted(line_summary.items(),key=lambda x:x[1]['unp'],reverse=True)[:10]
fig3,ax3=plt.subplots(figsize=(12,4.5))
ll=[l for l,_ in top_lines]; uv=[d['unp']/60 for _,d in top_lines]; tv=[d['total']/60 for _,d in top_lines]
pcts=[d['unp']/d['total']*100 if d['total'] else 0 for _,d in top_lines]
colors3=['#c0392b' if p>50 else '#e74c3c' if p>30 else '#f39c12' for p in pcts]
x=np.arange(len(ll)); w=0.35
ax3.barh(x+w/2, uv, w, label='异常停机', color=colors3, edgecolor='white')
for i,(u,t,p) in enumerate(zip(uv,tv,pcts)):
    ax3.text(u+0.3, i, f'{u:.0f}h ({p:.0f}%)', va='center', fontsize=9)
ax3.set_yticks(x); ax3.set_yticklabels(ll,fontsize=10)
ax3.set_title('异常停机 TOP 10 产线(排除计划)',fontweight='bold'); ax3.grid(axis='x',alpha=.3); ax3.invert_yaxis()
fig3.tight_layout(); chart3=fig2b64(fig3)

# Chart 4: Model top 10 by unplanned
top_models=sorted(model_summary.items(),key=lambda x:x[1]['unp'],reverse=True)[:10]
fig4,ax4=plt.subplots(figsize=(12,4.5))
ml=[m[:30] for m,_ in top_models]; uv4=[d['unp']/60 for _,d in top_models]
pcts4=[d['unp']/d['total']*100 if d['total'] else 0 for _,d in top_models]
colors4=['#c0392b' if p>50 else '#e74c3c' if p>30 else '#f39c12' for p in pcts4]
ax4.barh(range(len(ml)), uv4, color=colors4, edgecolor='white')
for i,(u,p) in enumerate(zip(uv4,pcts4)):
    ax4.text(u+0.3, i, f'{u:.0f}h ({p:.0f}%)', va='center', fontsize=9)
ax4.set_yticks(range(len(ml))); ax4.set_yticklabels(ml,fontsize=9)
ax4.set_title('异常停机 TOP 10 机种(排除计划)',fontweight='bold'); ax4.grid(axis='x',alpha=.3); ax4.invert_yaxis()
fig4.tight_layout(); chart4=fig2b64(fig4)

# ====== HTML ======
# Week table
wr=""
for w in week_summary:
    c='#c0392b' if w['unp_pct']>50 else '#e74c3c' if w['unp_pct']>30 else '#f39c12'
    wr+=f"<tr><td>W{w['week']}</td><td class='n'>{w['count']}</td><td class='n'>{w['total']/60:.0f}h</td><td class='n'>{w['prod']/60:.0f}h</td><td class='n'>{w['unp']/60:.0f}h</td><td class='a' style='color:{c}'>{w['unp_pct']:.1f}%</td></tr>"

# Kes table
KORDER=["冲压一课","冲压二课","冲压三课"]
kr=""
for k in KORDER:
    d=dept_summary.get(k)
    if d and d['total']>0:
        p=d['unp']/d['total']*100; c='#c0392b' if p>50 else '#e74c3c' if p>30 else '#f39c12'
        kr+=f"<tr><td>{k}</td><td class='n'>{d['total']/60:.0f}h</td><td class='n'>{d['prod']/60:.0f}h</td><td class='n'>{d['unp']/60:.0f}h</td><td class='a' style='color:{c}'>{p:.1f}%</td></tr>"

# Cats table
cr=""
for k,v in sorted(all_cats.items(),key=lambda x:x[1],reverse=True):
    p=v/total_u*100 if total_u else 0
    cr+=f"<tr><td>{k}</td><td class='n'>{v/60:.1f}h</td><td class='n'>{p:.1f}%</td></tr>"

# Weekly detail by kes
wdr=""
for w in week_summary:
    for k in KORDER:
        kd=w['kes'].get(k)
        if kd and kd['total']>0:
            p=kd['unp']/kd['total']*100 if kd['total'] else 0
            c='#e74c3c' if p>30 else '#f39c12' if p>10 else '#27ae60'
            wdr+=f"<tr><td>W{w['week']}</td><td>{k}</td><td class='n'>{kd['total']/60:.0f}h</td><td class='n'>{kd['prod']/60:.0f}h</td><td class='n'>{kd['unp']/60:.0f}h</td><td class='a' style='color:{c}'>{p:.1f}%</td></tr>"

# Model table
mr=""
for m,d in sorted(model_summary.items(),key=lambda x:x[1]['unp'],reverse=True)[:15]:
    p=d['unp']/d['total']*100 if d['total'] else 0; c='#c0392b' if p>50 else '#e74c3c' if p>30 else '#f39c12'
    mr+=f"<tr><td>{m[:40]}</td><td>{len(d['lines'])}</td><td class='n'>{d['total']/60:.0f}h</td><td class='n'>{d['prod']/60:.0f}h</td><td class='n'>{d['unp']/60:.0f}h</td><td class='a' style='color:{c}'>{p:.1f}%</td></tr>"

now=datetime.now()
ach_c='#e74c3c' if total_u/total_t*100>30 else '#f39c12' if total_u/total_t*100>10 else '#27ae60'

html=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>制造一部异常工时周分析</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;-webkit-user-select:text;user-select:text}}
.c{{max-width:1300px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:20px 28px;border-radius:14px;margin-bottom:18px}}
.hd h1{{font-size:21px}}.hd .m{{font-size:12px;opacity:.8;margin-top:4px}}
.kr{{display:flex;gap:10px;margin-bottom:18px}}
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
.tw{{max-height:400px;overflow-y:auto}}
@media(max-width:900px){{.gr{{grid-template-columns:1fr}}.kr{{flex-wrap:wrap}}}}
</style></head><body><div class="c">
<div class="hd"><h1>制造一部 异常工时周分析</h1><div class="m">范围: 仅制造一部(NA/NB) | 排除计划停机/管理时间 | {len(records)}条 | {len(weeks)}周 | 生成:{now.strftime('%Y-%m-%d %H:%M')}</div></div>

<div class="kr">
<div class="kc"><div class="l">记录数</div><div class="v" style="color:#3498db">{len(records)}</div><div class="s">条(仅制造一部)</div></div>
<div class="kc"><div class="l">有效生产</div><div class="v" style="color:#27ae60">{total_p/60:.0f}h</div><div class="s">{total_p/total_t*100:.1f}%</div></div>
<div class="kc"><div class="l">异常停机</div><div class="v" style="color:{ach_c}">{total_u/60:.0f}h</div><div class="s">{total_u/total_t*100:.1f}%</div></div>
<div class="kc"><div class="l">周数</div><div class="v" style="color:#9b59b6">{len(weeks)}</div><div class="s">{weeks[0]}~{weeks[-1]}周</div></div>
</div>

<div class="sc"><h2>每周 生产 vs 异常停机</h2><img src="data:image/png;base64,{chart1}"></div>

<div class="gr">
<div class="sc"><h2>异常类别(排除计划)</h2><img src="data:image/png;base64,{chart2}"></div>
<div class="sc"><h2>每周汇总</h2><table><thead><tr><th>周</th><th>记录</th><th>总工时</th><th>生产</th><th>异常</th><th>异常率</th></tr></thead><tbody>{wr}</tbody></table></div>
</div>

<div class="sc"><h2>异常停机 TOP 10 产线</h2><img src="data:image/png;base64,{chart3}"></div>

<div class="sc"><h2>异常停机 TOP 10 机种</h2><img src="data:image/png;base64,{chart4}"></div>

<div class="gr">
<div class="sc"><h2>课别汇总</h2><table><thead><tr><th>课别</th><th>总工时</th><th>生产</th><th>异常</th><th>异常率</th></tr></thead><tbody>{kr}</tbody></table></div>
<div class="sc"><h2>异常类别明细</h2><div class="tw"><table><thead><tr><th>类别</th><th>时长</th><th>占比</th></tr></thead><tbody>{cr}</tbody></table></div></div>
</div>

<div class="sc"><h2>每周 × 课别 交叉明细</h2><div class="tw"><table><thead><tr><th>周</th><th>课别</th><th>总工时</th><th>生产</th><th>异常</th><th>异常率</th></tr></thead><tbody>{wdr}</tbody></table></div></div>

<div class="sc"><h2>机种异常 TOP 15</h2><div class="tw"><table><thead><tr><th>机种</th><th>产线数</th><th>总工时</th><th>生产</th><th>异常</th><th>异常率</th></tr></thead><tbody>{mr}</tbody></table></div></div>

</div></body></html>"""

nm=f"异常工时分析_{now.strftime('%Y%m%d_%H%M')}.html"
op=OUT/nm; op.parent.mkdir(parents=True,exist_ok=True); op.write_text(html,encoding='utf-8')
print(f"✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{nm}")
print(f"\n摘要:")
print(f"  制造一部: {len(records)}条, {len(weeks)}周 (W{weeks[0]}~W{weeks[-1]})")
print(f"  生产: {total_p/60:.0f}h ({total_p/total_t*100:.1f}%) | 异常: {total_u/60:.0f}h ({total_u/total_t*100:.1f}%)")
print(f"  TOP3 异常: {', '.join(f'{k}({v/60:.0f}h)' for k,v in sorted(all_cats.items(),key=lambda x:x[1],reverse=True)[:3])}")

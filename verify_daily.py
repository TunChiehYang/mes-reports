#!/usr/bin/env python3
"""单次日报分析 — 7/2 08:30 数据"""
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

SRC = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY/V_PLAN_ACTUAL_SUMMARY_20260702_083038.csv")
OUT = Path("/mnt/d/outputHTML")

df = pd.read_csv(SRC, encoding='gbk')
df['PLANQTY'] = pd.to_numeric(df['PLANQTY'], errors='coerce').fillna(0).astype(int)
df['AUTOQTY'] = pd.to_numeric(df['AUTOQTY'], errors='coerce').fillna(0).astype(int)
df['NOTE'] = df['NOTE'].fillna('').str.strip()

def parse_ach(v):
    try: return float(str(v).replace('%','').strip())
    except: return 0

df['ACH_NUM'] = df['ACH'].apply(parse_ach)

df_norm = df[df['NOTE']=='正常'].copy()
df_noprod = df[df['NOTE']=='无生产'].copy()

def get_dept(line):
    line=str(line).strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$',line): return ("制造一部","冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$',line): return ("制造一部","冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$',line): return ("制造一部","冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$',line): return ("制造二部","清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$',line): return ("制造二部","清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$',line): return ("制造二部","清洗三课")
    return ("未分类","未分类")

# ====== Aggregation ======
all_plan = int(df['PLANQTY'].sum())
all_auto = int(df['AUTOQTY'].sum())
norm_plan = int(df_norm['PLANQTY'].sum())
norm_auto = int(df_norm['AUTOQTY'].sum())
norm_ach = norm_auto/norm_plan*100 if norm_plan else 0
noprod_plan = int(df_noprod['PLANQTY'].sum())

# Dept summary (normal only)
dept_data = defaultdict(lambda:{'plan':0,'auto':0,'lines':set()})
for _,r in df_norm.iterrows():
    d,k=get_dept(r['LINE_ID']); dept_data[(d,k)]['plan']+=r['PLANQTY']; dept_data[(d,k)]['auto']+=r['AUTOQTY']; dept_data[(d,k)]['lines'].add(r['LINE_ID'])

# Line summary
line_data=defaultdict(lambda:{'plan':0,'auto':0,'models':set(),'wo':set(),'ach_list':[]})
for _,r in df_norm.iterrows():
    l=r['LINE_ID']; line_data[l]['plan']+=r['PLANQTY']; line_data[l]['auto']+=r['AUTOQTY']
    line_data[l]['ach_list'].append(r['ACH_NUM'])
    m=str(r.get('ACTUAL_MODEL_LIST','')).strip()
    if m: 
        for x in m.split('/'): line_data[l]['models'].add(x.strip())
    w=str(r.get('PLAN_WO_ID_SINGLE','')).strip()
    if w: line_data[l]['wo'].add(w)

for l in line_data:
    al=line_data[l]['ach_list']; line_data[l]['ach']=sum(al)/len(al) if al else 0

# Top/bottom
sorted_lines=sorted(line_data.items(),key=lambda x:x[1]['ach'],reverse=True)
top5=[(l,d) for l,d in sorted_lines if d['plan']>0][:5]
bottom5=[(l,d) for l,d in sorted_lines if d['plan']>0][-5:]

# ====== Charts ======
def fig2b64(fig):
    b=io.BytesIO(); fig.savefig(b,format='png',dpi=130,bbox_inches='tight',facecolor='white')
    b.seek(0); r=base64.b64encode(b.read()).decode(); plt.close(fig); return r

# Chart 1: Dept bar
DEPT_ORDER=[("制造一部","冲压一课"),("制造一部","冲压二课"),("制造一部","冲压三课"),("制造二部","清洗一课"),("制造二部","清洗二课"),("制造二部","清洗三课")]
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(14,5))
labels=[]; ach_vals=[]; plan_vals=[]; auto_vals=[]
for dk in DEPT_ORDER:
    dd=dept_data.get(dk)
    if dd and dd['plan']>0:
        labels.append(dk[1]); ach=dd['auto']/dd['plan']*100; ach_vals.append(ach); plan_vals.append(dd['plan']); auto_vals.append(dd['auto'])
colors=['#e74c3c' if a<30 else '#f39c12' if a<60 else '#27ae60' for a in ach_vals]
bars=ax1.barh(range(len(labels)),ach_vals,color=colors,edgecolor='white')
for b,ach in zip(bars,ach_vals): ax1.text(b.get_width()+1,b.get_y()+b.get_height()/2,f'{ach:.1f}%',va='center',fontsize=10,fontweight='bold')
ax1.set_yticks(range(len(labels))); ax1.set_yticklabels(labels,fontsize=10); ax1.set_title('部门达成率',fontweight='bold'); ax1.set_xlim(0,max(ach_vals)*1.3 if max(ach_vals)>0 else 100); ax1.grid(axis='x',alpha=.3); ax1.invert_yaxis()
x=np.arange(len(labels)); w=0.35
ax2.barh(x+w/2,plan_vals,w,label='计划',color='#3498db',alpha=.85); ax2.barh(x-w/2,auto_vals,w,label='实际',color='#27ae60',alpha=.85)
ax2.set_yticks(x); ax2.set_yticklabels(labels,fontsize=10); ax2.set_title('计划 vs 实际',fontweight='bold'); ax2.legend(fontsize=9); ax2.grid(axis='x',alpha=.3); ax2.invert_yaxis()
fig.tight_layout(); chart1=fig2b64(fig)

# Chart 2: Status pie
fig2,ax=plt.subplots(figsize=(6,4))
status_labels=['正常','无生产','不正常']
status_vals=[len(df_norm),len(df_noprod),len(df)-len(df_norm)-len(df_noprod)]
status_colors=['#27ae60','#e74c3c','#f39c12']
ax.pie(status_vals,labels=[f'{l}\n({v}条)' for l,v in zip(status_labels,status_vals)],colors=status_colors,autopct='%1.1f%%',startangle=90)
ax.set_title('生产状态分布',fontweight='bold')
fig2.tight_layout(); chart2=fig2b64(fig2)

# Chart 3: Line ACH top15
fig3,ax3=plt.subplots(figsize=(12,6))
top15=sorted_lines[:15]
t_labels=[l for l,_ in top15]; t_vals=[d['ach'] for _,d in top15]
colors3=['#e74c3c' if v<30 else '#f39c12' if v<60 else '#27ae60' for v in t_vals]
bars3=ax3.barh(range(len(t_labels)),t_vals,color=colors3,edgecolor='white')
for b,v in zip(bars3,t_vals): ax3.text(b.get_width()+1,b.get_y()+b.get_height()/2,f'{v:.1f}%',va='center',fontsize=9)
ax3.set_yticks(range(len(t_labels))); ax3.set_yticklabels(t_labels,fontsize=9)
ax3.set_title('产线达成率 TOP 15',fontweight='bold'); ax3.set_xlim(0,max(t_vals)*1.2 if max(t_vals)>0 else 100); ax3.grid(axis='x',alpha=.3); ax3.invert_yaxis()
fig3.tight_layout(); chart3=fig2b64(fig3)

# ====== HTML ======
# Dept table
dr=""
for dk in DEPT_ORDER:
    dd=dept_data.get(dk)
    if dd and dd['plan']>0:
        ach=dd['auto']/dd['plan']*100; c='#e74c3c' if ach<30 else '#f39c12' if ach<60 else '#27ae60'
        dr+=f"<tr><td>{dk[0]}</td><td>{dk[1]}</td><td>{len(dd['lines'])}</td><td class='n'>{dd['plan']:,}</td><td class='n'>{dd['auto']:,}</td><td class='a' style='color:{c}'>{ach:.1f}%</td></tr>"

# Line detail grouped
DEPTS=["制造一部","制造二部"]; KES={"制造一部":["冲压一课","冲压二课","冲压三课"],"制造二部":["清洗一课","清洗二课","清洗三课"]}
lr=""
for dept in DEPTS:
    for kes in KES[dept]:
        glines=[(l,d) for l,d in line_data.items() if get_dept(l)==(dept,kes)]
        if not glines: continue
        glines.sort(key=lambda x:x[1]['ach'],reverse=True)
        gp=sum(d['plan'] for _,d in glines); ga=sum(d['auto'] for _,d in glines)
        gach=ga/gp*100 if gp else 0; gc='#e74c3c' if gach<30 else '#f39c12' if gach<60 else '#27ae60'
        lr+=f"""<tr style='background:#f0f4f8;font-weight:700'>
            <td colspan='2'>{dept} · {kes}</td><td>{len(glines)}条</td><td class='n'>{gp:,}</td><td class='n'>{ga:,}</td><td class='a' style='color:{gc}'>{gach:.1f}%</td></tr>"""
        for l,d in glines:
            ach=d['ach']; ac='#e74c3c' if ach==0 else '#27ae60' if ach>=60 else '#f39c12'
            models='/'.join(sorted(d['models'])[:2]) if d['models'] else '-'
            lr+=f"<tr><td>{l}</td><td style='font-size:12px'>{models[:30]}</td><td>{','.join(sorted(d['wo'])[:2])[:24]}</td><td class='n'>{d['plan']:,}</td><td class='n'>{d['auto']:,}</td><td class='a' style='color:{ac}'>{ach:.1f}%</td></tr>"

# Top/bottom tables
def tbl_rows(items):
    return ''.join(f"<tr><td>{l}</td><td style='font-size:12px'>{'/'.join(sorted(d['models'])[:2])[:30]}</td><td class='n'>{d['plan']:,}</td><td class='n'>{d['auto']:,}</td><td class='a'>{d['ach']:.1f}%</td></tr>" for l,d in items)

# Noprod lines
noprod_lines = df_noprod.groupby('LINE_ID').agg({'PLANQTY':'sum','AUTOQTY':'sum'}).reset_index()
noprod_lines = noprod_lines[noprod_lines['PLANQTY']>0].sort_values('PLANQTY',ascending=False)
noprod_html=''
for _,r in noprod_lines.iterrows():
    noprod_html+=f"<tr><td>{r['LINE_ID']}</td><td class='n'>{int(r['PLANQTY']):,}</td></tr>"

now=datetime.now()
ach_c='#e74c3c' if norm_ach<30 else '#f39c12' if norm_ach<60 else '#27ae60'

html=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>生产日报校验 - 2026-07-02 08:30</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;-webkit-user-select:text;user-select:text}}
.c{{max-width:1300px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:24px 32px;border-radius:14px;margin-bottom:20px}}
.hd h1{{font-size:22px}}.hd .m{{font-size:12px;opacity:.8;margin-top:4px}}
.kr{{display:flex;gap:12px;margin-bottom:20px}}
.kc{{flex:1;background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 2px 8px rgba(0,0,0,.06);text-align:center}}
.kc .l{{font-size:12px;color:#888}}.kc .v{{font-size:24px;font-weight:700;margin:2px 0}}.kc .s{{font-size:11px;color:#aaa}}
.sc{{background:#fff;border-radius:10px;padding:18px 22px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.sc h2{{font-size:15px;color:#1a1a2e;margin-bottom:12px;padding-bottom:6px;border-bottom:2px solid #3498db}}
img{{max-width:100%;border-radius:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f8f9fa;padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6}}
td{{padding:6px 10px;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9ff}}.n{{text-align:right}}.a{{text-align:right;font-weight:600}}
.tw{{max-height:500px;overflow-y:auto}}
.gr{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:900px){{.gr{{grid-template-columns:1fr}}.kr{{flex-wrap:wrap}}}}
.note{{background:#fff3cd;border:1px solid #ffc107;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px}}
</style></head><body><div class="c">
<div class="hd"><h1>生产日报数据校验</h1><div class="m">文件: V_PLAN_ACTUAL_SUMMARY_20260702_083038.csv | {len(df)}行 | 正常{len(df_norm)}行 无生产{len(df_noprod)}行 | 生成:{now.strftime('%Y-%m-%d %H:%M')}</div></div>

<div class="note">⚠ <b>校验说明：</b>本报告基于原始 CSV 文件独立计算 PLANQTY 和 AUTOQTY，用于与自动生成的日报交叉比对。仅统计 <b>NOTE='正常'</b> 的行参与达成率计算。</div>

<div class="kr">
<div class="kc"><div class="l">计划总量(全部)</div><div class="v" style="color:#3498db">{all_plan:,}</div><div class="s">pcs</div></div>
<div class="kc"><div class="l">实际总量(全部)</div><div class="v" style="color:#27ae60">{all_auto:,}</div><div class="s">pcs</div></div>
<div class="kc"><div class="l">正常行计划</div><div class="v" style="color:#2980b9">{norm_plan:,}</div><div class="s">pcs ({len(df_norm)}行)</div></div>
<div class="kc"><div class="l">正常行实际</div><div class="v" style="color:#27ae60">{norm_auto:,}</div><div class="s">pcs</div></div>
<div class="kc"><div class="l">正常行达成率</div><div class="v" style="color:{ach_c}">{norm_ach:.1f}%</div><div class="s">{'🔴预警' if norm_ach<30 else '🟡偏低' if norm_ach<60 else '🟢正常'}</div></div>
<div class="kc"><div class="l">未生产计划</div><div class="v" style="color:#e74c3c">{noprod_plan:,}</div><div class="s">{len(df_noprod)}行无生产</div></div>
</div>

<div class="sc"><h2>生产状态分布 & 部门达成率</h2>
<div class="gr"><img src="data:image/png;base64,{chart2}"><img src="data:image/png;base64,{chart1}"></div></div>

<div class="sc"><h2>产线达成率 TOP 15</h2><img src="data:image/png;base64,{chart3}"></div>

<div class="gr">
<div class="sc"><h2>部门汇总（仅正常）</h2><table><thead><tr><th>部门</th><th>课别</th><th>产线</th><th>计划</th><th>实际</th><th>达成率</th></tr></thead><tbody>{dr}</tbody></table></div>
<div class="sc"><h2>TOP 5 / 末位 5</h2>
<h3 style="font-size:13px;color:#27ae60;margin:8px 0 4px">🏆 达成率 TOP 5</h3>
<table><thead><tr><th>产线</th><th>机型</th><th>计划</th><th>实际</th><th>达成率</th></tr></thead><tbody>{tbl_rows(top5)}</tbody></table>
<h3 style="font-size:13px;color:#e74c3c;margin:12px 0 4px">⚠ 达成率 末位 5</h3>
<table><thead><tr><th>产线</th><th>机型</th><th>计划</th><th>实际</th><th>达成率</th></tr></thead><tbody>{tbl_rows(bottom5)}</tbody></table>
</div>
</div>

<div class="sc"><h2>产线明细（按部门分组 · 达成率排序 · 仅正常）</h2>
<div class="tw"><table><thead><tr><th>产线</th><th>机型</th><th>工单</th><th>计划</th><th>实际</th><th>达成率</th></tr></thead><tbody>{lr}</tbody></table></div></div>

<div class="sc"><h2>无生产产线（{len(noprod_lines)}条有计划的未生产）</h2>
<div class="tw"><table><thead><tr><th>产线</th><th>计划量</th></tr></thead><tbody>{noprod_html}</tbody></table></div></div>

</div></body></html>"""

out_name=f"日报校验_20260702_0830.html"
op=OUT/out_name; op.parent.mkdir(parents=True,exist_ok=True); op.write_text(html,encoding='utf-8')
print(f"✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{out_name}")
print(f"\n数据汇总:")
print(f"  全部: 计划={all_plan:,} 实际={all_auto:,}")
print(f"  正常({len(df_norm)}行): 计划={norm_plan:,} 实际={norm_auto:,} 达成率={norm_ach:.1f}%")
print(f"  无生产({len(df_noprod)}行): 计划={noprod_plan:,}")

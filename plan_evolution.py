#!/usr/bin/env python3
"""7月计划表演进分析 — 对比今天所有版本"""
import pandas as pd
import re, io, base64
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

for fname in ['WenQuanYi Zen Hei', 'Noto Sans CJK SC']:
    if fname in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams['font.family'] = fname; break
plt.rcParams['axes.unicode_minus'] = False

PLAN_DIR = Path("/mnt/d/ShareExport/output/V_MONTH_PLAN")
OUT_DIR = Path("/mnt/d/outputHTML")

# 支持命令行参数指定日期，默认今天
import sys
target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y%m%d')
files = sorted(PLAN_DIR.glob(f"V_MONTH_PLAN_{target_date}_*.csv"))
print(f"今天共 {len(files)} 个版本")

def get_dept(line):
    line = str(line).strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$', line): return ("制造一部","冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$', line): return ("制造一部","冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$', line): return ("制造一部","冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$', line): return ("制造二部","清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$', line): return ("制造二部","清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$', line): return ("制造二部","清洗三课")
    return ("未分类","未分类")

versions = []
for f in files:
    df = pd.read_csv(f, encoding='utf-8-sig')
    df.columns = [c.strip().strip('"') for c in df.columns]
    df['RUNCARD_QTY'] = pd.to_numeric(df['RUNCARD_QTY'], errors='coerce').fillna(0).astype(int)
    tl = f.stem.split('_')[-1][:4]
    versions.append({'time':tl,'file':f.name,'df':df,
        'total_qty':int(df['RUNCARD_QTY'].sum()),'total_lines':len(df),
        'wo_count':df['WO_ID'].nunique(),'model_count':df['MODEL_NO'].nunique()})
    print(f"  {tl}: {len(df)}行 {df['RUNCARD_QTY'].sum():,}pcs")

# Dept trend
dept_trend = defaultdict(list)
for v in versions:
    dq = defaultdict(int)
    for _,r in v['df'].iterrows():
        d,k = get_dept(r['LINE_ID']); dq[(d,k)] += int(r['RUNCARD_QTY'])
    for (d,k),q in dq.items(): dept_trend[f"{d}-{k}"].append((v['time'],q))

# Changes between versions
changes = []
for i in range(1,len(versions)):
    p,c = versions[i-1], versions[i]
    pl = p['df'].groupby('LINE_ID')['RUNCARD_QTY'].sum()
    cl = c['df'].groupby('LINE_ID')['RUNCARD_QTY'].sum()
    all_l = set(pl.index)|set(cl.index)
    added = set(cl.index)-set(pl.index)
    removed = set(pl.index)-set(cl.index)
    chg = []
    for l in set(pl.index)&set(cl.index):
        if pl[l]!=cl[l]: chg.append((l,pl[l],cl[l],cl[l]-pl[l]))
    changes.append({'from':p['time'],'to':c['time'],'added':len(added),
        'removed':len(removed),'changed':len(chg),
        'added_lines':sorted(added),
        'changed_lines':sorted(chg,key=lambda x:abs(x[3]),reverse=True)[:10]})

def fig2b64(fig):
    buf=io.BytesIO(); fig.savefig(buf,format='png',dpi=130,bbox_inches='tight',facecolor='white')
    buf.seek(0); r=base64.b64encode(buf.read()).decode(); plt.close(fig); return r

# Chart 1: Total trend
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(14,5))
ts=[v['time'] for v in versions]; qs=[v['total_qty'] for v in versions]
ax1.plot(ts,[q/10000 for q in qs],'o-',color='#3498db',lw=2,ms=8)
for t,q in zip(ts,qs): ax1.annotate(f'{q/10000:.1f}万',(t,q/10000),textcoords="offset points",xytext=(0,10),ha='center',fontsize=8)
ax1.set_ylabel('计划总量(万件)'); ax1.set_title('总量趋势',fontweight='bold'); ax1.grid(alpha=.3)

# Chart 2: Dept stacked
DEPT_ORDER=["制造一部-冲压一课","制造一部-冲压二课","制造一部-冲压三课","制造二部-清洗一课","制造二部-清洗二课","制造二部-清洗三课"]
COLORS=['#3498db','#2980b9','#1a5276','#e74c3c','#c0392b','#922b21']
for k,c in zip(DEPT_ORDER,COLORS):
    if k in dept_trend:
        pts=dept_trend[k]; ax2.plot([p[0] for p in pts],[p[1]/10000 for p in pts],'o-',color=c,lw=1.5,label=k,ms=5)
ax2.set_ylabel('计划量(万件)'); ax2.set_title('各部门变化',fontweight='bold')
ax2.legend(fontsize=7,ncol=2); ax2.grid(alpha=.3)
fig.tight_layout(); chart1=fig2b64(fig)

# HTML
now=datetime.now()
vr="".join(f"<tr><td>{v['time']}</td><td class='n'>{v['total_lines']}</td><td class='n'>{v['total_qty']:,}</td><td class='n'>{v['wo_count']}</td><td class='n'>{v['model_count']}</td><td>{v['file']}</td></tr>" for v in versions)
cr=""
for c in changes:
    det=""; 
    if c['changed_lines']: det="<br>".join(f"{l}: {o:,}→{n:,} ({'+' if d>0 else ''}{d:,})" for l,o,n,d in c['changed_lines'][:5])
    cr+=f"<tr><td>{c['from']}→{c['to']}</td><td class='n'>{c['added']}</td><td class='n'>{c['removed']}</td><td class='n'>{c['changed']}</td><td style='font-size:12px'>{det}</td></tr>"

html=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>7月计划表演进 - {target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'WenQuanYi Zen Hei','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;-webkit-user-select:text;user-select:text}}
.c{{max-width:1200px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:24px 32px;border-radius:14px;margin-bottom:20px}}
.hd h1{{font-size:22px}} .hd .m{{font-size:12px;opacity:.8;margin-top:4px}}
.kr{{display:flex;gap:12px;margin-bottom:20px}}
.kc{{flex:1;background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 2px 8px rgba(0,0,0,.06);text-align:center}}
.kc .l{{font-size:12px;color:#888}} .kc .v{{font-size:22px;font-weight:700;margin:2px 0}} .kc .s{{font-size:11px;color:#aaa}}
.sc{{background:#fff;border-radius:10px;padding:18px 22px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.sc h2{{font-size:15px;color:#1a1a2e;margin-bottom:12px;padding-bottom:6px;border-bottom:2px solid #3498db}}
img{{max-width:100%;border-radius:6px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f8f9fa;padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6}}
td{{padding:6px 10px;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9ff}} .n{{text-align:right}}
</style></head><body><div class="c">
<div class="hd"><h1>7月计划表演进分析</h1><div class="m">2026-07-01 | {len(versions)}个版本 | 生成:{now.strftime('%H:%M')}</div></div>
<div class="kr">
<div class="kc"><div class="l">版本数</div><div class="v" style="color:#3498db">{len(versions)}</div><div class="s">每小时更新</div></div>
<div class="kc"><div class="l">最新总量</div><div class="v" style="color:#27ae60">{versions[-1]['total_qty']/10000:.1f}万</div><div class="s">pcs</div></div>
<div class="kc"><div class="l">最新产线</div><div class="v" style="color:#9b59b6">{versions[-1]['total_lines']}</div><div class="s">条</div></div>
<div class="kc"><div class="l">最新工单</div><div class="v" style="color:#f39c12">{versions[-1]['wo_count']}</div><div class="s">个</div></div>
</div>
<div class="sc"><h2>总量 & 部门趋势</h2><img src="data:image/png;base64,{chart1}"></div>
<div class="sc"><h2>版本快照</h2><table><thead><tr><th>时间</th><th>行数</th><th>计划总量</th><th>工单数</th><th>机型数</th><th>文件名</th></tr></thead><tbody>{vr}</tbody></table></div>
<div class="sc"><h2>版本间变化</h2><table><thead><tr><th>变化区间</th><th>新增</th><th>减少</th><th>变更</th><th>主要变化(Top5)</th></tr></thead><tbody>{cr}</tbody></table></div>
</div></body></html>"""

op=OUT_DIR/f"月计划演进_{now.strftime('%Y%m%d_%H%M')}.html"
op.parent.mkdir(parents=True,exist_ok=True); op.write_text(html,encoding='utf-8')
print(f"\n✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{op.name}")

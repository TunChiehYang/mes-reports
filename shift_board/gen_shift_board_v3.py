#!/usr/bin/env python3
"""当班生产趋势看板 v3 - 聚焦近3天生产趋势"""
import json
from pathlib import Path
from datetime import datetime, timedelta

HTML_DIR = Path("/mnt/d/outputHTML")
data = json.loads(open(HTML_DIR / "当班趋势数据_v2.json", encoding='utf-8').read())
records = data['records']

# 按班次分组
from collections import defaultdict
shift_data = defaultdict(list)
for r in records:
    if r['shift_group'] == '夜班' and r['hour'] < 8:
        sd = (datetime.fromisoformat(r['dt']) - timedelta(days=1)).strftime('%m/%d')
    else:
        sd = r['date']
    shift_data[(sd, r['shift_group'])].append(r)

shifts = []
for (sd, sg), recs in sorted(shift_data.items()):
    last = recs[-1]
    shifts.append({
        'date': sd, 'shift': sg,
        'plan': last['total_plan'], 'done': last['total_done'], 'ach': last['total_ach'],
        'dept1_plan': last['dept1_plan'], 'dept1_done': last['dept1_done'], 'dept1_ach': last['dept1_ach'],
        'dept2_plan': last['dept2_plan'], 'dept2_done': last['dept2_done'], 'dept2_ach': last['dept2_ach'],
        'active': last['active_lines'], 'idle': last['idle_lines'], 'total': last['total_lines'],
        'snaps': [{'h': s['hour'], 'm': int(s['dt'][14:16]), 't': s['time'],
                    'done': s['total_done'], 'd1d': s['dept1_done'], 'd2d': s['dept2_done'],
                    'ach': s['total_ach'], 'd1a': s['dept1_ach'], 'd2a': s['dept2_ach'],
                    'active': s['active_lines']} for s in recs],
    })

now_str = datetime.now().strftime('%Y%m%d_%H%M%S')

# 过滤有效班次（有产出且近3天）
valid = [s for s in shifts if s['done'] > 0]

def fmt(n):
    return f"{n:,}"

# 找颜色
shift_colors = {
    ('07/06','白班'): '#f0883e',
    ('07/06','夜班'): '#e85d26',
    ('07/07','白班'): '#58a6ff',
    ('07/07','夜班'): '#388bfd',
}
fallback_colors = ['#f0883e','#e85d26','#58a6ff','#388bfd','#3fb950','#8957e5']

# 生成
html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>当班生产趋势分析</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Microsoft YaHei','WenQuanYi Zen Hei',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}}
.topbar{{background:#161b22;border-bottom:1px solid #21262d;padding:14px 24px;display:flex;justify-content:space-between;align-items:center}}
.topbar h1{{font-size:17px;color:#f0f6fc}}
.topbar span{{font-size:11px;color:#8b949e}}
.container{{max-width:1400px;margin:0 auto;padding:14px 18px}}

/* KPI条 */
.kpi-strip{{display:flex;gap:10px;margin-bottom:14px}}
.kpi{{flex:1;background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 16px;text-align:center}}
.kpi .lbl{{font-size:10px;color:#8b949e;margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px}}
.kpi .val{{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}}
.kpi .sub{{font-size:10px;color:#6e7681;margin-top:1px}}

/* 面板 */
.panel{{background:#161b22;border:1px solid #21262d;border-radius:10px;margin-bottom:14px;overflow:hidden}}
.panel-hd{{padding:10px 18px;border-bottom:1px solid #21262d;font-size:12px;font-weight:600;color:#f0f6fc;display:flex;align-items:center;gap:8px}}
.panel-bd{{padding:14px 18px}}

/* SVG */
.chart-svg{{width:100%}}
.g-line{{stroke:#30363d;stroke-width:1}}
.g-text{{fill:#8b949e;font-size:10px;font-family:inherit}}
.g-grid{{stroke:#1a1f26;stroke-width:1;stroke-dasharray:4,4}}

/* 标签 */
.tag{{display:inline-block;padding:1px 8px;border-radius:8px;font-size:10px;font-weight:600;line-height:1.4}}
.t-day{{background:#3d2e1a;color:#f0883e}}
.t-night{{background:#1c2128;color:#8b949e;border:1px solid #30363d}}

/* 表格 */
table{{width:100%;border-collapse:collapse;font-size:11px}}
th{{background:#1c2128;padding:7px 10px;text-align:left;font-weight:600;border-bottom:2px solid #30363d;color:#8b949e;white-space:nowrap}}
td{{padding:6px 10px;border-bottom:1px solid #21262d;white-space:nowrap}}
tr:hover td{{background:#1c2128}}
.n{{text-align:right;font-variant-numeric:tabular-nums}}

/* 进度条 */
.pbar{{background:#21262d;border-radius:3px;height:6px;overflow:hidden;min-width:50px;margin-top:2px}}
.pbar-in{{height:100%;border-radius:3px}}

/* 响应式 */
@media(max-width:800px){{.kpi-strip{{flex-wrap:wrap}}.kpi{{min-width:30%}}}}

.footer{{text-align:center;padding:14px;color:#484f58;font-size:10px}}
</style>
</head>
<body>

<div class="topbar">
<h1>当班生产趋势分析</h1>
<span>每2小时快照 · 近3天 · 白班8-20 / 夜班20-8 · 最新: {records[-1]['date']} {records[-1]['time']} · 生成 {now_str}</span>
</div>

<div class="container">

<!-- KPI 条 -->
<div class="kpi-strip" id="kpiStrip"></div>

<!-- 生产累进曲线（核心图表） -->
<div class="panel">
<div class="panel-hd">⏱ 全厂生产累进曲线 — 每个班次内产出增长趋势（2h快照连线）</div>
<div class="panel-bd"><div id="accumAll"></div></div>
</div>

<!-- 双部门对比 -->
<div class="panel">
<div class="panel-hd">📊 达成率趋势 — 最近6个班次 制造一部 vs 制造二部</div>
<div class="panel-bd"><div id="trendDept"></div></div>
</div>

<!-- 班次明细表 -->
<div class="panel">
<div class="panel-hd">📋 班次结算明细</div>
<div class="panel-bd"><table><thead><tr>
<th>日期</th><th>班次</th><th>快照数</th><th>全厂计划</th><th>全厂完成</th><th>达成率</th>
<th>制造一部 计划</th><th>制造一部 完成</th><th>制造一部 达成</th>
<th>制造二部 计划</th><th>制造二部 完成</th><th>制造二部 达成</th>
<th>有产出/总产线</th><th>未开动</th>
</tr></thead><tbody id="shiftBody"></tbody></table></div>
</div>

</div>
<div class="footer">MES 生产数据分析平台 · 当班趋势看板</div>

<script>
var shifts = {json.dumps(shifts, ensure_ascii=False)};

// ===== KPI 条 =====
(function(){{
    if(!shifts.length)return;
    var latest=shifts[shifts.length-1];
    var prev=shifts.length>1?shifts[shifts.length-2]:null;
    var arr=prev&&latest.ach>=prev.ach?'&#9650;':'&#9660;';
    var diff=prev?(latest.ach-prev.ach).toFixed(1):'0';
    var sgn=prev&&latest.ach>=prev.ach?'+':'';
    
    var html='';
    html+='<div class="kpi"><div class="lbl">当前班次</div><div class="val" style="font-size:16px;color:#58a6ff">'+latest.date+' <span class="tag '+(latest.shift==='白班'?'t-day':'t-night')+'">'+latest.shift+'</span></div><div class="sub">'+latest.snaps.length+'次快照</div></div>';
    html+='<div class="kpi"><div class="lbl">全厂计划</div><div class="val" style="color:#8b949e">'+fmt(latest.plan)+'</div><div class="sub">件</div></div>';
    html+='<div class="kpi"><div class="lbl">全厂完成</div><div class="val" style="color:#f0f6fc">'+fmt(latest.done)+'</div><div class="sub">件</div></div>';
    html+='<div class="kpi"><div class="lbl">达成率</div><div class="val" style="color:'+(latest.ach>=30?'#3fb950':'#d29922')+'">'+latest.ach.toFixed(1)+'% '+arr+'</div><div class="sub">较上班 '+sgn+diff+'%</div></div>';
    html+='<div class="kpi"><div class="lbl">制造一部达成</div><div class="val" style="color:#58a6ff">'+latest.dept1_ach.toFixed(1)+'%</div><div class="sub">'+fmt(latest.dept1_done)+' / '+fmt(latest.dept1_plan)+' 件</div></div>';
    html+='<div class="kpi"><div class="lbl">制造二部达成</div><div class="val" style="color:#3fb950">'+latest.dept2_ach.toFixed(1)+'%</div><div class="sub">'+fmt(latest.dept2_done)+' / '+fmt(latest.dept2_plan)+' 件</div></div>';
    html+='<div class="kpi"><div class="lbl">产线开动</div><div class="val" style="color:'+(latest.active>=latest.total/2?'#3fb950':'#d29922')+'">'+latest.active+'<span style="font-size:14px;color:#6e7681">/'+latest.total+'</span></div><div class="sub">未开动 '+latest.idle+' 条</div></div>';
    document.getElementById('kpiStrip').innerHTML=html;
}})();

function fmt(n){{return n.toString().replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,',');}}

// ===== 累进曲线 =====
(function(){{
    var valid=shifts.filter(function(s){{return s.done>0 && s.snaps&&s.snaps.length>=2;}});
    if(valid.length<2){{document.getElementById('accumAll').innerHTML='<p style="color:#484f58;text-align:center;padding:50px">数据不足</p>';return;}}
    
    var colors=['#f0883e','#e85d26','#58a6ff','#388bfd','#3fb950','#8957e5'];
    
    // 统一时间轴: 找所有班次的小时范围
    var allH=[],maxDone=0;
    for(var i=0;i<valid.length;i++){{
        var s=valid[i].snaps;
        for(var j=0;j<s.length;j++){{allH.push(s[j].h+s[j].m/60);if(s[j].done>maxDone)maxDone=s[j].done;}}
    }}
    var hMin=Math.floor(Math.min.apply(null,allH));
    var hMax=Math.ceil(Math.max.apply(null,allH))+1;
    maxDone=Math.ceil(maxDone/20000)*20000+20000;
    
    var w=1200,h=350,ml=60,mr=15,mt=15,mb=45;
    var pw=w-ml-mr,ph=h-mt-mb;
    var svg='<svg class="chart-svg" viewBox="0 0 '+w+' '+h+'"><g transform="translate('+ml+','+mt+')">';
    
    // 网格+Y轴
    for(var i=0;i<=4;i++){{
        var y=ph-(i/4*ph);
        svg+='<line x1="0" y1="'+y+'" x2="'+pw+'" y2="'+y+'" class="g-grid"/>';
        svg+='<text x="-8" y="'+(y+4)+'" class="g-text" text-anchor="end">'+fmt(Math.round(maxDone*i/4))+'</text>';
    }}
    svg+='<text x="'+(pw/2)+'" y="'+(ph+28)+'" class="g-text" text-anchor="middle" font-size="9" fill="#484f58">时刻（小时）</text>';
    
    // X轴
    for(var h=Math.floor(hMin/2)*2;h<=hMax;h+=2){{
        var x=(h-hMin)/(hMax-hMin)*pw;
        svg+='<line x1="'+x+'" y1="0" x2="'+x+'" y2="'+ph+'" class="g-grid" opacity="0.3"/>';
        svg+='<text x="'+x+'" y="'+(ph+14)+'" class="g-text" text-anchor="middle">'+h.toString().padStart(2,'0')+':00</text>';
    }}
    
    // 绘制每条线
    for(var i=0;i<valid.length;i++){{
        var pts=valid[i].snaps;
        var c=colors[i%colors.length];
        var path='',area='';
        for(var j=0;j<pts.length;j++){{
            var x=(pts[j].h+pts[j].m/60-hMin)/(hMax-hMin)*pw;
            var y=ph-(pts[j].done/maxDone*ph);
            path+=(j===0?'M':'L')+x+','+y+' ';
            area+=(j===0?'M':'L')+x+','+y+' ';
        }}
        area+='L'+(pw)+','+ph+' L0,'+ph+' Z';
        svg+='<path d="'+area+'" fill="'+c+'" opacity="0.06"/>';
        svg+='<path d="'+path+'" stroke="'+c+'" stroke-width="2.5" fill="none"/>';
        // 最后一个点
        var lp=pts[pts.length-1];
        var lx=(lp.h+lp.m/60-hMin)/(hMax-hMin)*pw;
        var ly=ph-(lp.done/maxDone*ph);
        svg+='<circle cx="'+lx+'" cy="'+ly+'" r="4" fill="'+c+'" stroke="#0d1117" stroke-width="2"><title>'+valid[i].date+' '+valid[i].shift+' 完成:'+fmt(lp.done)+'件 ('+lp.ach.toFixed(1)+'%)</title></circle>';
    }}
    
    // 图例
    for(var i=0;i<valid.length;i++){{
        svg+='<rect x="'+(i*110)+'" y="-12" width="10" height="10" rx="2" fill="'+colors[i%colors.length]+'"/>';
        svg+='<text x="'+(i*110+14)+'" y="-3" class="g-text">'+valid[i].date+' '+valid[i].shift+'</text>';
    }}
    
    svg+='</g></svg>';
    document.getElementById('accumAll').innerHTML=svg;
}})();

// ===== 达成率趋势（双线对比） =====
(function(){{
    var valid=shifts.filter(function(s){{return s.done>0;}});
    if(valid.length<2){{document.getElementById('trendDept').innerHTML='';return;}}
    
    var w=1200,h=240,ml=55,mr=15,mt=15,mb=40;
    var pw=w-ml-mr,ph=h-mt-mb,n=valid.length;
    var svg='<svg class="chart-svg" viewBox="0 0 '+w+' '+h+'"><g transform="translate('+ml+','+mt+')">';
    
    for(var i=0;i<=4;i++){{
        var y=ph-(i/4*ph);
        svg+='<line x1="0" y1="'+y+'" x2="'+pw+'" y2="'+y+'" class="g-grid"/>';
        svg+='<text x="-8" y="'+(y+4)+'" class="g-text" text-anchor="end">'+(i*25)+'%</text>';
    }}
    
    // 一部线
    var p1='',p2='';
    for(var i=0;i<n;i++){{
        var x=i/(n-1)*pw;
        var y1=ph-(valid[i].dept1_ach/100*ph);
        var y2=ph-(valid[i].dept2_ach/100*ph);
        p1+=(i===0?'M':'L')+x+','+y1+' ';
        p2+=(i===0?'M':'L')+x+','+y2+' ';
        svg+='<circle cx="'+x+'" cy="'+y1+'" r="3" fill="#58a6ff"><title>'+valid[i].date+' '+valid[i].shift+' 制造一部:'+valid[i].dept1_ach.toFixed(1)+'%</title></circle>';
        svg+='<circle cx="'+x+'" cy="'+y2+'" r="3" fill="#3fb950"><title>'+valid[i].date+' '+valid[i].shift+' 制造二部:'+valid[i].dept2_ach.toFixed(1)+'%</title></circle>';
    }}
    svg+='<path d="'+p1+'" stroke="#58a6ff" stroke-width="2" fill="none"/>';
    svg+='<path d="'+p2+'" stroke="#3fb950" stroke-width="2" fill="none"/>';
    
    var step=Math.max(1,Math.floor(n/7));
    for(var i=0;i<n;i+=step){{
        var x=i/(n-1)*pw;
        svg+='<text x="'+x+'" y="'+(ph+15)+'" class="g-text" text-anchor="middle">'+valid[i].date+'</text>';
        svg+='<text x="'+x+'" y="'+(ph+27)+'" class="g-text" text-anchor="middle" font-size="9" fill="#484f58">'+valid[i].shift+'</text>';
    }}
    
    svg+='<rect x="10" y="-12" width="10" height="10" rx="2" fill="#58a6ff"/><text x="24" y="-3" class="g-text">制造一部（冲压）</text>';
    svg+='<rect x="120" y="-12" width="10" height="10" rx="2" fill="#3fb950"/><text x="134" y="-3" class="g-text">制造二部（清洗）</text>';
    
    svg+='</g></svg>';
    document.getElementById('trendDept').innerHTML=svg;
}})();

// ===== 明细表 =====
(function(){{
    var rows='';
    for(var i=shifts.length-1;i>=0;i--){{
        var s=shifts[i];
        var aC=s.ach>=30?'#3fb950':(s.ach>=15?'#d29922':'#f85149');
        var d1c=s.dept1_ach>=50?'#3fb950':(s.dept1_ach>=25?'#d29922':'#8b949e');
        var d2c=s.dept2_ach>=20?'#3fb950':(s.dept2_ach>=10?'#d29922':'#8b949e');
        
        rows+='<tr>'+
            '<td>'+s.date+'</td>'+
            '<td><span class="tag '+(s.shift==='白班'?'t-day':'t-night')+'">'+s.shift+'</span></td>'+
            '<td class="n" style="color:#6e7681">'+s.snaps.length+'</td>'+
            '<td class="n" style="color:#8b949e">'+fmt(s.plan)+'</td>'+
            '<td class="n" style="color:#f0f6fc;font-weight:600">'+fmt(s.done)+'</td>'+
            '<td class="n" style="color:'+aC+';font-weight:700">'+s.ach.toFixed(1)+'%<div class="pbar"><div class="pbar-in" style="width:'+Math.min(s.ach,100)+'%;background:'+aC+'"></div></div></td>'+
            '<td class="n" style="color:#8b949e">'+fmt(s.dept1_plan)+'</td>'+
            '<td class="n" style="color:#58a6ff">'+fmt(s.dept1_done)+'</td>'+
            '<td class="n" style="color:'+d1c+'">'+s.dept1_ach.toFixed(1)+'%</td>'+
            '<td class="n" style="color:#8b949e">'+fmt(s.dept2_plan)+'</td>'+
            '<td class="n" style="color:#3fb950">'+fmt(s.dept2_done)+'</td>'+
            '<td class="n" style="color:'+d2c+'">'+s.dept2_ach.toFixed(1)+'%</td>'+
            '<td class="n">'+s.active+' / '+s.total+'</td>'+
            '<td class="n" style="color:#f85149">'+s.idle+'</td>'+
            '</tr>';
    }}
    document.getElementById('shiftBody').innerHTML=rows;
}})();
</script>
</body>
</html>'''

output = HTML_DIR / f"当班趋势看板_{now_str}.html"
output.write_text(html, encoding='utf-8')
print(f"看板已生成: {output}")
print(f"大小: {output.stat().st_size:,} bytes")

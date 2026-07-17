#!/usr/bin/env python3
"""当班生产趋势看板 v2 - 制造一部/制造二部分开展示 + 仅近3天"""
import json
from pathlib import Path
from datetime import datetime, timedelta

HTML_DIR = Path("/mnt/d/outputHTML")
JSON_PATH = HTML_DIR / "当班趋势数据.json"

if not JSON_PATH.exists():
    print("请先运行数据解析脚本")
    exit(1)

data = json.loads(JSON_PATH.read_text(encoding='utf-8'))
records = data['records']

# 过滤：仅最近3天
now = datetime.now()
cutoff = now - timedelta(days=3)
recent = [r for r in records if datetime.fromisoformat(r['dt']) >= cutoff]

# 按班次分组
from collections import defaultdict
shift_data = defaultdict(list)  # key: (date, shift_group)
for r in recent:
    if r['shift_group'] == '夜班' and r['hour'] < 8:
        sd = (datetime.fromisoformat(r['dt']) - timedelta(days=1)).strftime('%m/%d')
    else:
        sd = r['date']
    shift_data[(sd, r['shift_group'])].append(r)

# 整理为有序列表
shifts = []
for (sd, sg), recs in sorted(shift_data.items(), key=lambda x: (x[0][0], 0 if x[0][1]=='白班' else 1)):
    last = recs[-1]
    shifts.append({
        'date': sd, 'shift': sg,
        'plan': last['total_plan'], 'done': last['total_done'], 'ach': last['total_ach'],
        'dept1_plan': last['dept1_plan'], 'dept1_done': last['dept1_done'], 'dept1_ach': last['dept1_ach'],
        'dept2_plan': last['dept2_plan'], 'dept2_done': last['dept2_done'], 'dept2_ach': last['dept2_ach'],
        'active': last['active_lines'], 'idle': last['idle_lines'], 'total': last['total_lines'],
        'snaps': recs,
    })

# 过滤无产出班次
valid_shifts = [s for s in shifts if s['done'] > 0]

if not valid_shifts:
    print("近3天无有效数据")
    exit(1)

now_str = datetime.now().strftime('%Y%m%d_%H%M%S')

# 公共函数
def fmt(n):
    return f"{n:,}"

# 制造一部涵盖的产线前缀
DEPT1_LINES = ['NA','NB']
DEPT2_LINES = ['NQ']

# 构建 JS 数据
shifts_json = json.dumps(valid_shifts, ensure_ascii=False)
# 所有快照（含逐笔累进）
all_snaps_json = json.dumps(recent, ensure_ascii=False)

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>当班生产趋势看板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Microsoft YaHei','WenQuanYi Zen Hei',sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}}

/* 顶部 */
.topbar{{background:#161b22;border-bottom:1px solid #21262d;padding:16px 28px;display:flex;align-items:center;justify-content:space-between}}
.topbar h1{{font-size:18px;color:#f0f6fc;font-weight:600}}
.topbar .info{{font-size:11px;color:#8b949e}}
.topbar .shift-legend{{display:flex;gap:10px;font-size:11px;align-items:center}}
.legend-dot{{width:10px;height:10px;border-radius:3px;display:inline-block}}
.legend-day{{background:#f0883e}}
.legend-night{{background:#6e7681}}

.container{{max-width:1500px;margin:0 auto;padding:16px 20px}}

/* KPI 条 */
.kpi-strip{{display:flex;gap:10px;margin-bottom:16px}}
.kpi-item{{flex:1;background:#161b22;border:1px solid #21262d;border-radius:8px;padding:14px 18px;text-align:center}}
.kpi-item .label{{font-size:11px;color:#8b949e;margin-bottom:4px}}
.kpi-item .val{{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}}
.kpi-item .sub{{font-size:10px;color:#6e7681;margin-top:2px}}
.c-good .val{{color:#3fb950}}
.c-warn .val{{color:#d29922}}
.c-blue .val{{color:#58a6ff}}
.c-red .val{{color:#f85149}}

/* 面板 */
.panel{{background:#161b22;border:1px solid #21262d;border-radius:10px;margin-bottom:16px;overflow:hidden}}
.panel-header{{padding:12px 20px;border-bottom:1px solid #21262d;font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px;color:#f0f6fc}}
.panel-header .badge{{font-size:10px;padding:2px 8px;border-radius:8px;font-weight:500}}
.badge-dept1{{background:#1f3a5f;color:#58a6ff}}
.badge-dept2{{background:#1a3a1a;color:#3fb950}}
.panel-body{{padding:16px 20px;overflow-x:auto}}

/* 图表 SVG */
.chart-svg{{width:100%}}
.axis-line{{stroke:#30363d;stroke-width:1}}
.axis-text{{fill:#8b949e;font-size:10px;font-family:inherit}}
.grid-line{{stroke:#1a1f26;stroke-width:1;stroke-dasharray:4,4}}

/* 表格 */
table{{width:100%;border-collapse:collapse;font-size:12px}}
thead th{{position:sticky;top:0;background:#1c2128;padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid #30363d;color:#8b949e;white-space:nowrap;z-index:1}}
tbody td{{padding:7px 10px;border-bottom:1px solid #21262d;white-space:nowrap}}
tbody tr:hover td{{background:#1c2128}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}

/* 产线明细表 */
.line-table-wrap{{max-height:500px;overflow-y:auto}}
.line-table td{{font-size:11px}}

/* 进度条 */
.pbar{{background:#21262d;border-radius:3px;height:7px;overflow:hidden;margin-top:3px;min-width:60px}}
.pbar-inner{{height:100%;border-radius:3px;transition:width .3s}}

/* 班次标签 */
.tag{{display:inline-block;padding:1px 8px;border-radius:8px;font-size:10px;font-weight:600}}
.tag-day{{background:#3d2e1a;color:#f0883e}}
.tag-night{{background:#1c2128;color:#8b949e;border:1px solid #30363d}}

/* 趋势小卡片 */
.trend-row{{display:flex;gap:12px;margin-bottom:16px}}
.trend-card{{flex:1;background:#161b22;border:1px solid #21262d;border-radius:8px;padding:16px}}
.trend-card h3{{font-size:12px;color:#8b949e;margin-bottom:12px;font-weight:500}}
.trend-bars{{display:flex;align-items:flex-end;gap:3px;height:80px;padding-top:4px}}
.trend-bar{{flex:1;border-radius:2px 2px 0 0;position:relative;min-width:12px}}
.trend-bar:hover{{opacity:.85}}
.trend-bar .tt{{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);background:#21262d;color:#f0f6fc;padding:3px 8px;border-radius:4px;font-size:10px;white-space:nowrap;display:none;margin-bottom:4px}}
.trend-bar:hover .tt{{display:block}}

.footer{{text-align:center;padding:16px;color:#484f58;font-size:11px}}

/* 双列布局 */
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:1000px){{.cols{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

<div class="topbar">
  <div>
    <h1>当班生产趋势看板</h1>
    <div class="info">每2小时快照 · 近3天 · 白班8-20 / 夜班20-8 · 生成 {now_str}</div>
  </div>
  <div class="shift-legend">
    <span><span class="legend-dot legend-day"></span> 白班</span>
    <span><span class="legend-dot legend-night"></span> 夜班</span>
  </div>
</div>

<div class="container">

<!-- KPI 概览条 -->
<div class="kpi-strip" id="kpiStrip"></div>

<!-- 左右分栏：制造一部 | 制造二部 -->
<div class="cols">

<!-- ========== 制造一部 ========== -->
<div>
<div class="panel">
  <div class="panel-header">🏭 制造一部（冲压）<span class="badge badge-dept1">NA / NB 线</span></div>
  <div class="panel-body" id="dept1KPI"></div>
</div>
<div class="panel">
  <div class="panel-header">📈 制造一部 · 达成率趋势</div>
  <div class="panel-body"><div id="dept1Trend"></div></div>
</div>
<div class="panel">
  <div class="panel-header">⏱ 制造一部 · 班次内累进（最近3个班次）</div>
  <div class="panel-body"><div id="dept1Accum"></div></div>
</div>
</div>

<!-- ========== 制造二部 ========== -->
<div>
<div class="panel">
  <div class="panel-header">🏭 制造二部（清洗）<span class="badge badge-dept2">NQ 线</span></div>
  <div class="panel-body" id="dept2KPI"></div>
</div>
<div class="panel">
  <div class="panel-header">📈 制造二部 · 达成率趋势</div>
  <div class="panel-body"><div id="dept2Trend"></div></div>
</div>
<div class="panel">
  <div class="panel-header">⏱ 制造二部 · 班次内累进（最近3个班次）</div>
  <div class="panel-body"><div id="dept2Accum"></div></div>
</div>
</div>

</div>

<!-- 班次汇总表 -->
<div class="panel">
  <div class="panel-header">📋 班次明细（近3天）</div>
  <div class="panel-body"><table><thead><tr>
    <th>日期</th><th>班次</th><th>计划总产量</th><th>完成总产量</th><th>全厂达成率</th>
    <th>制造一部 完成</th><th>制造一部 达成</th>
    <th>制造二部 完成</th><th>制造二部 达成</th>
    <th>有产出/总产线</th>
  </tr></thead><tbody id="shiftTableBody"></tbody></table></div>
</div>

</div>
<div class="footer">MES 生产数据分析平台 · 当班趋势看板</div>

<script>
var shifts = {shifts_json};
var snaps = {all_snaps_json};

// ===== 工具函数 =====
function fmt(n) {{ return n.toString().replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ','); }}

// ===== 顶部 KPI 条 =====
(function() {{
    if (!shifts.length) return;
    var latest = shifts[shifts.length-1];
    var prev = shifts.length>1 ? shifts[shifts.length-2] : null;
    var trendAch = prev ? (latest.ach - prev.ach).toFixed(1) : '0';
    var trendArrow = prev && latest.ach>=prev.ach ? '&#9650;' : '&#9660;';
    var sign = prev && latest.ach>=prev.ach ? '+' : '';
    
    document.getElementById('kpiStrip').innerHTML =
        '<div class="kpi-item c-blue"><div class="label">当前班次</div><div class="val" style="font-size:18px">'+latest.date+' <span class="tag '+(latest.shift==='白班'?'tag-day':'tag-night')+'">'+latest.shift+'</span></div><div class="sub">共 '+latest.snaps.length+' 次快照</div></div>'+
        '<div class="kpi-item c-blue"><div class="label">全厂计划 / 完成</div><div class="val" style="font-size:18px">'+fmt(latest.plan)+' / '+fmt(latest.done)+'</div><div class="sub">件</div></div>'+
        '<div class="kpi-item '+(latest.ach>=30?'c-good':'c-warn')+'"><div class="label">全厂达成率</div><div class="val">'+latest.ach.toFixed(1)+'% '+trendArrow+'</div><div class="sub">较上班 '+sign+trendAch+'%</div></div>'+
        '<div class="kpi-item c-blue"><div class="label">制造一部达成率</div><div class="val">'+latest.dept1_ach.toFixed(1)+'%</div><div class="sub">完成 '+fmt(latest.dept1_done)+' / 计划 '+fmt(latest.dept1_plan)+'</div></div>'+
        '<div class="kpi-item c-blue"><div class="label">制造二部达成率</div><div class="val">'+latest.dept2_ach.toFixed(1)+'%</div><div class="sub">完成 '+fmt(latest.dept2_done)+' / 计划 '+fmt(latest.dept2_plan)+'</div></div>'+
        '<div class="kpi-item '+(latest.active>=latest.total/2?'c-good':'c-warn')+'"><div class="label">产线开动</div><div class="val">'+latest.active+' <span style="font-size:14px;color:#8b949e">/ '+latest.total+'</span></div><div class="sub">未开动 '+latest.idle+' 条</div></div>';
}})();

// ===== 部门 KPI 小卡片 =====
function renderDeptKPI(dept) {{
    var valid = shifts.filter(function(s){{return s.done>0;}});
    var recent = valid.slice(-6);
    var deptName = dept===1 ? '制造一部' : '制造二部';
    var planKey = dept===1 ? 'dept1_plan' : 'dept2_plan';
    var doneKey = dept===1 ? 'dept1_done' : 'dept2_done';
    var achKey = dept===1 ? 'dept1_ach' : 'dept2_ach';
    
    var bars = '';
    var maxAch = Math.max.apply(null, recent.map(function(s){{return s[achKey];}}));
    maxAch = Math.max(maxAch, 10);
    
    for (var i=0; i<recent.length; i++) {{
        var s = recent[i];
        var h = Math.max(4, (s[achKey]/maxAch)*80);
        var color = dept===1 ? '#58a6ff' : '#3fb950';
        if (s[achKey] < 15) color = '#f0883e';
        if (s[achKey] < 5) color = '#6e7681';
        var tagClass = s.shift==='白班' ? 'tag-day' : 'tag-night';
        bars += '<div class="trend-bar" style="height:'+h+'px;background:'+color+'">'+
            '<div class="tt">'+s.date+'<br>'+s.shift+'<br>'+s[achKey].toFixed(1)+'%<br>'+fmt(s[doneKey])+'件</div></div>';
    }}
    
    document.getElementById('dept'+dept+'KPI').innerHTML =
        '<div style="font-size:11px;color:#8b949e;margin-bottom:8px">最近6个班次达成率（柱高=达成率）</div>'+
        '<div class="trend-bars">'+bars+'</div>'+
        '<div style="display:flex;justify-content:space-between;font-size:9px;color:#484f58;margin-top:4px">'+
        recent.map(function(s){{return '<span>'+s.date+'<br>'+s.shift+'</span>';}}).join('')+'</div>';
}}

// ===== 达成率趋势折线图 =====
function renderTrendChart(dept, containerId) {{
    var valid = shifts.filter(function(s){{return s.done>0;}});
    if (valid.length < 2) {{ document.getElementById(containerId).innerHTML = '<p style="color:#484f58;text-align:center;padding:40px">数据不足</p>'; return; }}
    
    var achKey = dept===1 ? 'dept1_ach' : 'dept2_ach';
    var n = valid.length;
    var w = 700, h = 240, ml=55, mr=15, mt=15, mb=40;
    var plotW = w - ml - mr, plotH = h - mt - mb;
    var maxAch = 100;
    
    var svg = '<svg class="chart-svg" viewBox="0 0 '+w+' '+h+'">';
    svg += '<g transform="translate('+ml+','+mt+')">';
    
    // 网格
    for (var i=0; i<=4; i++) {{
        var y = plotH - (i/4*plotH);
        svg += '<line x1="0" y1="'+y+'" x2="'+plotW+'" y2="'+y+'" class="grid-line"/>';
        svg += '<text x="-8" y="'+(y+4)+'" class="axis-text" text-anchor="end">'+(i*25)+'%</text>';
    }}
    svg += '<line x1="0" y1="'+plotH+'" x2="'+plotW+'" y2="'+plotH+'" class="axis-line"/>';
    
    // 折线 + 填充
    var path = '', area = '', dots = '';
    var color = dept===1 ? '#58a6ff' : '#3fb950';
    
    for (var i=0; i<n; i++) {{
        var x = i / (n-1) * plotW;
        var y = plotH - (valid[i][achKey] / maxAch * plotH);
        path += (i===0?'M':'L') + x + ',' + y + ' ';
        area += (i===0?'M':'L') + x + ',' + y + ' ';
        dots += '<circle cx="'+x+'" cy="'+y+'" r="3.5" fill="'+color+'"><title>'+valid[i].date+' '+valid[i].shift+' 达成率:'+valid[i][achKey].toFixed(1)+'%</title></circle>';
    }}
    area += 'L'+plotW+','+plotH+' L0,'+plotH+' Z';
    
    svg += '<path d="'+area+'" fill="'+color+'" opacity="0.08"/>';
    svg += '<path d="'+path+'" stroke="'+color+'" stroke-width="2" fill="none"/>';
    svg += dots;
    
    // X 轴标签
    var step = Math.max(1, Math.floor(n/8));
    for (var i=0; i<n; i+=step) {{
        var x = i / (n-1) * plotW;
        svg += '<text x="'+x+'" y="'+(plotH+16)+'" class="axis-text" text-anchor="middle">'+valid[i].date+'</text>';
        svg += '<text x="'+x+'" y="'+(plotH+28)+'" class="axis-text" text-anchor="middle">'+valid[i].shift+'</text>';
    }}
    // 最后一个
    if (n>1 && (n-1)%step !== 0) {{
        var x = plotW;
        svg += '<text x="'+x+'" y="'+(plotH+16)+'" class="axis-text" text-anchor="middle">'+valid[n-1].date+'</text>';
        svg += '<text x="'+x+'" y="'+(plotH+28)+'" class="axis-text" text-anchor="middle">'+valid[n-1].shift+'</text>';
    }}
    
    svg += '</g></svg>';
    document.getElementById(containerId).innerHTML = svg;
}}

// ===== 累进曲线（最近3个班次） =====
function renderAccumChart(dept, containerId) {{
    var planKey = dept===1 ? 'dept1_plan' : 'dept2_plan';
    var doneKey = dept===1 ? 'dept1_done' : 'dept2_done';
    var achKey  = dept===1 ? 'dept1_ach' : 'dept2_ach';
    
    var valid = shifts.filter(function(s){{return s.done>0;}});
    if (valid.length === 0) return;
    
    var last = valid.slice(-3);
    var colors = dept===1 ? ['#58a6ff','#3fb950','#f0883e'] : ['#3fb950','#58a6ff','#f0883e'];
    
    // 找每个班次的快照
    var shiftSnaps = [];
    var maxVal = 0;
    for (var s=0; s<last.length; s++) {{
        var snaps = last[s].snaps || [];
        if (snaps.length===0) continue;
        
        var pts = [];
        for (var j=0; j<snaps.length; j++) {{
            var val = snaps[j][doneKey];
            if (val > maxVal) maxVal = val;
            var dt = snaps[j].dt;
            var h = parseInt(dt.substring(11,13)) + parseInt(dt.substring(14,16))/60;
            pts.push({{h:h, val:val, ach:snaps[j][achKey], time:dt.substring(11,16)}});
        }}
        shiftSnaps.push({{label:last[s].date+' '+last[s].shift, pts:pts, color:colors[s]}});
    }}
    
    if (maxVal===0 || shiftSnaps.length===0) {{ document.getElementById(containerId).innerHTML = '<p style="color:#484f58;text-align:center;padding:40px">暂无累进数据</p>'; return; }}
    maxVal = Math.ceil(maxVal/10000)*10000 + 10000;
    
    var w=700, h=240, ml=60, mr=15, mt=10, mb=40;
    var pw=w-ml-mr, ph=h-mt-mb;
    
    // 找所有时间点
    var allH = [];
    for (var s=0; s<shiftSnaps.length; s++) {{
        for (var j=0; j<shiftSnaps[s].pts.length; j++) allH.push(shiftSnaps[s].pts[j].h);
    }}
    var hMin = Math.floor(Math.min.apply(null, allH));
    var hMax = Math.ceil(Math.max.apply(null, allH)) + 1;
    
    var svg = '<svg class="chart-svg" viewBox="0 0 '+w+' '+h+'">';
    svg += '<g transform="translate('+ml+','+mt+')">';
    
    for (var i=0; i<=4; i++) {{
        var y = ph - (i/4*ph);
        svg += '<line x1="0" y1="'+y+'" x2="'+pw+'" y2="'+y+'" class="grid-line"/>';
        svg += '<text x="-8" y="'+(y+4)+'" class="axis-text" text-anchor="end">'+fmt(Math.round(maxVal*i/4))+'件</text>';
    }}
    
    for (var s=0; s<shiftSnaps.length; s++) {{
        var pts = shiftSnaps[s].pts;
        if (pts.length<2) continue;
        var path='';
        for (var j=0; j<pts.length; j++) {{
            var x = (pts[j].h - hMin) / (hMax-hMin) * pw;
            var y = ph - (pts[j].val / maxVal * ph);
            path += (j===0?'M':'L')+x+','+y+' ';
        }}
        svg += '<path d="'+path+'" stroke="'+shiftSnaps[s].color+'" stroke-width="2" fill="none"/>';
        // 端点
        var lastPt = pts[pts.length-1];
        var lx = (lastPt.h - hMin) / (hMax-hMin) * pw;
        var ly = ph - (lastPt.val / maxVal * ph);
        svg += '<circle cx="'+lx+'" cy="'+ly+'" r="4" fill="'+shiftSnaps[s].color+'"><title>'+shiftSnaps[s].label+' 最终:'+fmt(lastPt.val)+'件 ('+lastPt.ach.toFixed(1)+'%)</title></circle>';
    }}
    
    // X 轴
    for (var h=Math.floor(hMin/2)*2; h<=hMax; h+=2) {{
        var x = (h - hMin) / (hMax-hMin) * pw;
        svg += '<text x="'+x+'" y="'+(ph+16)+'" class="axis-text" text-anchor="middle">'+h.toString().padStart(2,'0')+':00</text>';
    }}
    
    // 图例
    for (var s=0; s<shiftSnaps.length; s++) {{
        svg += '<rect x="'+(s*120)+'" y="-8" width="10" height="10" rx="2" fill="'+shiftSnaps[s].color+'"/>';
        svg += '<text x="'+(s*120+14)+'" y="1" class="axis-text">'+shiftSnaps[s].label+'</text>';
    }}
    
    svg += '</g></svg>';
    document.getElementById(containerId).innerHTML = svg;
}}

// ===== 班次汇总表 =====
function renderTable() {{
    var rows = '';
    for (var i=shifts.length-1; i>=0; i--) {{
        var s = shifts[i];
        var achColor = s.ach>=30 ? '#3fb950' : (s.ach>=15 ? '#d29922' : '#f85149');
        var d1Color = s.dept1_ach>=50 ? '#3fb950' : (s.dept1_ach>=25 ? '#d29922' : '#8b949e');
        var d2Color = s.dept2_ach>=20 ? '#3fb950' : (s.dept2_ach>=10 ? '#d29922' : '#8b949e');
        
        var d1Bar = '<div class="pbar"><div class="pbar-inner" style="width:'+Math.min(s.dept1_ach,100)+'%;background:'+d1Color+'"></div></div>';
        var d2Bar = '<div class="pbar"><div class="pbar-inner" style="width:'+Math.min(s.dept2_ach,100)+'%;background:'+d2Color+'"></div></div>';
        
        rows += '<tr>'+
            '<td>'+s.date+'</td>'+
            '<td><span class="tag '+(s.shift==='白班'?'tag-day':'tag-night')+'">'+s.shift+'</span></td>'+
            '<td class="num">'+fmt(s.plan)+'</td>'+
            '<td class="num" style="color:#f0f6fc;font-weight:600">'+fmt(s.done)+'</td>'+
            '<td class="num" style="color:'+achColor+';font-weight:700">'+s.ach.toFixed(1)+'%</td>'+
            '<td class="num" style="color:#58a6ff">'+fmt(s.dept1_done)+'</td>'+
            '<td class="num" style="color:'+d1Color+'">'+s.dept1_ach.toFixed(1)+'%'+d1Bar+'</td>'+
            '<td class="num" style="color:#3fb950">'+fmt(s.dept2_done)+'</td>'+
            '<td class="num" style="color:'+d2Color+'">'+s.dept2_ach.toFixed(1)+'%'+d2Bar+'</td>'+
            '<td class="num">'+s.active+' / '+s.total+'</td>'+
            '</tr>';
    }}
    document.getElementById('shiftTableBody').innerHTML = rows;
}}

// ===== 渲染全部 =====
renderDeptKPI(1);
renderDeptKPI(2);
renderTrendChart(1, 'dept1Trend');
renderTrendChart(2, 'dept2Trend');
renderAccumChart(1, 'dept1Accum');
renderAccumChart(2, 'dept2Accum');
renderTable();
</script>
</body>
</html>'''

output_path = HTML_DIR / f"当班趋势看板_{now_str}.html"
output_path.write_text(html, encoding='utf-8')
print(f"看板已生成: {output_path}")
print(f"文件大小: {output_path.stat().st_size:,} bytes")

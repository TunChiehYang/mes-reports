#!/usr/bin/env python3
"""生成当班生产趋势看板 - 纯 CSS/JS，无外部依赖"""
import json, re
from pathlib import Path
from datetime import datetime

HTML_DIR = Path("/mnt/d/outputHTML")
JSON_PATH = HTML_DIR / "当班趋势数据.json"

if not JSON_PATH.exists():
    print("请先运行数据解析脚本")
    exit(1)

data = json.loads(JSON_PATH.read_text(encoding='utf-8'))
shifts = data['shifts']
records = data['records']

# 过滤掉没有产出的班次
valid_shifts = [s for s in shifts if s['done'] > 0]

# 准备 JS 数据
shifts_json = json.dumps(valid_shifts, ensure_ascii=False)
records_json = json.dumps(records, ensure_ascii=False)

now_str = datetime.now().strftime('%Y%m%d_%H%M%S')

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>当班生产趋势看板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Microsoft YaHei','WenQuanYi Zen Hei',sans-serif;background:#0f1923;color:#e0e0e0;min-height:100vh}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e 50%,#0f3460);padding:20px 32px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 20px rgba(0,0,0,.4)}}
.header h1{{font-size:20px;color:#fff}}
.header .sub{{font-size:12px;opacity:.6}}
.container{{max-width:1500px;margin:0 auto;padding:20px}}

/* KPI 卡片 */
.kpi-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}}
.kpi-card{{background:#1a2332;border-radius:10px;padding:16px 20px;text-align:center;border:1px solid #2a3a4a}}
.kpi-card .label{{font-size:12px;color:#8899aa;margin-bottom:4px}}
.kpi-card .num{{font-size:26px;font-weight:800}}
.kpi-card .sub{{font-size:11px;color:#667788;margin-top:2px}}
.kpi-good .num{{color:#2ecc71}}
.kpi-warn .num{{color:#f39c12}}
.kpi-info .num{{color:#3498db}}

/* 面板 */
.panel{{background:#1a2332;border-radius:12px;border:1px solid #2a3a4a;margin-bottom:20px;overflow:hidden}}
.panel-header{{padding:14px 22px;border-bottom:1px solid #2a3a4a;font-size:14px;font-weight:700;display:flex;align-items:center;gap:8px;background:#1e2a3a}}
.panel-body{{padding:16px 22px;overflow-x:auto}}

/* 图表区 */
.chart-area{{position:relative;min-height:280px}}
.chart-svg{{width:100%;height:100%}}
.axis-line{{stroke:#2a3a4a;stroke-width:1}}
.axis-text{{fill:#667788;font-size:10px}}
.grid-line{{stroke:#1e2d3d;stroke-width:1;stroke-dasharray:4,4}}

/* 折线 */
.line-dept1{{stroke:#3498db;stroke-width:2.5;fill:none}}
.line-dept2{{stroke:#2ecc71;stroke-width:2.5;fill:none}}
.line-total{{stroke:#f39c12;stroke-width:2.5;fill:none;stroke-dasharray:6,3}}
.dot{{stroke-width:0}}
.dot-dept1{{fill:#3498db}}
.dot-dept2{{fill:#2ecc71}}
.dot-total{{fill:#f39c12}}

/* 柱状图 */
.bar-dept1{{fill:#3498db;opacity:.85}}
.bar-dept2{{fill:#2ecc71;opacity:.85}}
.bar-day{{fill:#f39c12;opacity:.9}}
.bar-night{{fill:#7f8c8d;opacity:.9}}

/* 标签 */
.tag{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:600}}
.tag-day{{background:#f39c12;color:#1a1a2e}}
.tag-night{{background:#5a6a7a;color:#e0e0e0}}

/* 进度条 */
.progress-bar{{background:#1e2d3d;border-radius:4px;height:9px;overflow:hidden;margin-top:4px}}
.progress-fill{{height:100%;border-radius:4px;transition:width .3s}}
.fill-blue{{background:linear-gradient(90deg,#2980b9,#3498db)}}
.fill-green{{background:linear-gradient(90deg,#27ae60,#2ecc71)}}

/* 表格 */
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#1e2a3a;padding:8px 10px;text-align:left;font-weight:600;border-bottom:2px solid #2a3a4a;color:#8899aa;white-space:nowrap}}
td{{padding:7px 10px;border-bottom:1px solid #1e2d3d;white-space:nowrap}}
tr:hover td{{background:#1e2a3a}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}

/* 响应式 */
@media(max-width:900px){{.kpi-grid{{grid-template-columns:repeat(3,1fr)}}}}

/* tooltip */
.tooltip{{position:absolute;background:#2c3e50;color:#fff;padding:8px 12px;border-radius:6px;font-size:11px;pointer-events:none;white-space:nowrap;z-index:10;box-shadow:0 4px 12px rgba(0,0,0,.4);display:none}}

.footer{{text-align:center;padding:16px;color:#556677;font-size:11px}}
</style>
</head>
<body>

<div class="header">
<div><h1>当班生产趋势看板</h1><div class="sub">每2小时快照 · 白班 8:00-20:00 / 夜班 20:00-8:00</div></div>
<div style="font-size:12px;color:#8899aa">数据: {records[0]['date']} ~ {records[-1]['date']} · {len(records)} 个快照 · 生成: {now_str}</div>
</div>

<div class="container">

<!-- KPI 概览 -->
<div class="kpi-grid" id="kpiCards"></div>

<!-- 班次趋势对比 -->
<div class="panel">
<div class="panel-header">📈 班次达成率趋势（每个班次最终结算值）</div>
<div class="panel-body"><div class="chart-area" id="shiftTrendChart"></div></div>
</div>

<!-- 部门对比 -->
<div class="panel">
<div class="panel-header">🏭 制造一部 vs 制造二部 达成率对比</div>
<div class="panel-body"><div class="chart-area" id="deptCompareChart"></div></div>
</div>

<!-- 班次内累进趋势（24h 双班） -->
<div class="panel">
<div class="panel-header">⏱ 最近 3 个班次内生产累进曲线（每2小时累计完成量）</div>
<div class="panel-body"><div class="chart-area" id="accumChart"></div></div>
</div>

<!-- 班次明细表 -->
<div class="panel">
<div class="panel-header">📋 班次明细汇总</div>
<div class="panel-body">
<table id="shiftTable"><thead><tr>
<th>日期</th><th>班次</th><th>计划产量</th><th>完成产量</th><th>达成率</th><th>制造一部</th><th>制造二部</th><th>有产出/总产线</th><th>未开动</th>
</tr></thead><tbody></tbody></table>
</div></div>

</div>
<div class="footer">MES 生产数据分析平台 · 当班趋势看板 · 白班8-20 / 夜班20-8</div>

<script>
var shifts = {shifts_json};
var records = {records_json};

// ===== KPI 卡片 =====
function renderKPI() {{
    if (shifts.length === 0) return;
    var latest = shifts[shifts.length - 1];
    var prev = shifts.length > 1 ? shifts[shifts.length - 2] : null;
    
    // 最近3个班次均值
    var recent = shifts.slice(-3);
    var avgAch = recent.reduce(function(s,x){{return s+x.ach}},0) / recent.length;
    var avgActive = Math.round(recent.reduce(function(s,x){{return s+x.active_lines}},0) / recent.length);
    var avgIdle = Math.round(recent.reduce(function(s,x){{return s+x.idle_lines}},0) / recent.length);
    
    var trendUp = prev ? (latest.ach >= prev.ach ? ' ↑' : ' ↓') : '';
    var trendAch = prev ? (latest.ach - prev.ach).toFixed(1) : '';
    var trendSign = prev && latest.ach >= prev.ach ? '+' : '';
    
    document.getElementById('kpiCards').innerHTML = 
        '<div class="kpi-card kpi-info"><div class="label">最近班次</div><div class="num">' + latest.date + ' ' + latest.shift + '</div><div class="sub">' + latest.report_count + ' 份报告</div></div>' +
        '<div class="kpi-card kpi-info"><div class="label">当班计划</div><div class="num">' + formatNum(latest.plan) + '</div><div class="sub">件</div></div>' +
        '<div class="kpi-card kpi-good"><div class="label">当班完成</div><div class="num">' + formatNum(latest.done) + '</div><div class="sub">件</div></div>' +
        '<div class="kpi-card ' + (latest.ach >= 30 ? 'kpi-good' : 'kpi-warn') + '"><div class="label">达成率</div><div class="num">' + latest.ach.toFixed(1) + '%' + trendUp + '</div><div class="sub">较上班 ' + trendSign + trendAch + '% | 近3班均值 ' + avgAch.toFixed(1) + '%</div></div>' +
        '<div class="kpi-card kpi-warn"><div class="label">产线状态</div><div class="num">' + avgActive + ' / ' + latest.total_lines + '</div><div class="sub">有产出/总产线 | 近3班均未开动 ' + avgIdle + ' 条</div></div>';
}}

function formatNum(n) {{ return n.toString().replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ','); }}

// ===== SVG 图表引擎 =====
function makeChart(id, w, h, margin) {{
    margin = margin || {{top:20,right:30,bottom:40,left:60}};
    var svg = '<svg class="chart-svg" viewBox="0 0 ' + (w+margin.left+margin.right) + ' ' + (h+margin.top+margin.bottom) + '">';
    svg += '<g transform="translate(' + margin.left + ',' + margin.top + ')">';
    // 网格
    for (var i=0; i<=5; i++) {{
        var y = h - (i/5*h);
        svg += '<line x1="0" y1="' + y + '" x2="' + w + '" y2="' + y + '" class="grid-line"/>';
    }}
    svg += '<line x1="0" y1="' + h + '" x2="' + w + '" y2="' + h + '" class="axis-line"/>';
    svg += '<line x1="0" y1="0" x2="0" y2="' + h + '" class="axis-line"/>';
    document.getElementById(id).innerHTML = svg;
    return {{id:id, w:w, h:h, margin:margin, svg:svg}};
}}

function closeChart(chart, yLabels) {{
    var svg = chart.svg;
    // Y 轴标签
    for (var i=0; i<=5; i++) {{
        var y = chart.h - (i/5*chart.h);
        svg += '<text x="-8" y="' + (y+4) + '" class="axis-text" text-anchor="end">' + yLabels[i] + '</text>';
    }}
    svg += '</g></svg>';
    document.getElementById(chart.id).innerHTML = svg;
}}

// ===== 1. 班次达成率趋势 =====
function renderShiftTrend() {{
    var valid = shifts.filter(function(s){{return s.done > 0;}});
    if (valid.length < 2) {{ document.getElementById('shiftTrendChart').innerHTML = '<p style="color:#556677;text-align:center;padding:60px">数据不足</p>'; return; }}
    
    var ch = makeChart('shiftTrendChart', 1400, 320);
    var n = valid.length;
    var xStep = ch.w / (n-1);
    var maxAch = 100;
    
    // X 轴标签
    for (var i=0; i<n; i++) {{
        var x = i * xStep;
        // 每隔几个标一个
        if (i % Math.max(1,Math.floor(n/10)) === 0 || i === n-1) {{
            ch.svg += '<text x="' + x + '" y="' + (ch.h+20) + '" class="axis-text" text-anchor="middle">' + valid[i].date + '<tspan x="' + x + '" dy="12">' + valid[i].shift + '</tspan></text>';
        }}
    }}
    
    // 制造一部线
    var path1 = '', path2 = '', dots = '';
    for (var i=0; i<n; i++) {{
        var x = i * xStep;
        var y1 = ch.h - (valid[i].dept1_ach / maxAch * ch.h);
        var y2 = ch.h - (valid[i].dept2_ach / maxAch * ch.h);
        path1 += (i===0?'M':'L') + x + ',' + y1 + ' ';
        path2 += (i===0?'M':'L') + x + ',' + y2 + ' ';
        dots += '<circle cx="' + x + '" cy="' + y1 + '" r="3" class="dot dot-dept1"><title>' + valid[i].date + ' ' + valid[i].shift + ' 制造一部:' + valid[i].dept1_ach.toFixed(1) + '%</title></circle>';
        dots += '<circle cx="' + x + '" cy="' + y2 + '" r="3" class="dot dot-dept2"><title>' + valid[i].date + ' ' + valid[i].shift + ' 制造二部:' + valid[i].dept2_ach.toFixed(1) + '%</title></circle>';
    }}
    ch.svg += '<path d="' + path1 + '" class="line-dept1"/>';
    ch.svg += '<path d="' + path2 + '" class="line-dept2"/>';
    ch.svg += dots;
    
    // 图例
    ch.svg += '<rect x="10" y="-14" width="12" height="3" rx="1" class="line-dept1" style="stroke-width:3"/>';
    ch.svg += '<text x="28" y="-8" class="axis-text">制造一部</text>';
    ch.svg += '<rect x="80" y="-14" width="12" height="3" rx="1" class="line-dept2" style="stroke-width:3"/>';
    ch.svg += '<text x="98" y="-8" class="axis-text">制造二部</text>';
    
    closeChart(ch, ['0%','20%','40%','60%','80%','100%']);
}}

// ===== 2. 部门对比柱状图 =====
function renderDeptCompare() {{
    var valid = shifts.filter(function(s){{return s.done > 0;}});
    if (valid.length === 0) {{ document.getElementById('deptCompareChart').innerHTML = ''; return; }}
    var recent = valid.slice(-10);
    var n = recent.length;
    var w = 1200, h = 280, margin = {{top:20,right:30,bottom:50,left:60}};
    var barW = Math.min(30, (w - margin.left - margin.right) / (n*2) - 4);
    
    var svg = '<svg class="chart-svg" viewBox="0 0 ' + (w+margin.left+margin.right) + ' ' + (h+margin.top+margin.bottom) + '">';
    svg += '<g transform="translate(' + margin.left + ',' + margin.top + ')">';
    
    for (var i=0; i<=5; i++) {{
        var y = h - (i/5*h);
        svg += '<line x1="0" y1="' + y + '" x2="' + w + '" y2="' + y + '" class="grid-line"/>';
    }}
    
    for (var i=0; i<n; i++) {{
        var x = i * (w/n) + (w/n/2) - barW;
        var h1 = recent[i].dept1_ach / 100 * h;
        var h2 = recent[i].dept2_ach / 100 * h;
        svg += '<rect x="' + (x) + '" y="' + (h-h1) + '" width="' + barW + '" height="' + h1 + '" class="bar-dept1"><title>' + recent[i].date + ' ' + recent[i].shift + ' 制造一部:' + recent[i].dept1_ach.toFixed(1) + '%</title></rect>';
        svg += '<rect x="' + (x+barW+2) + '" y="' + (h-h2) + '" width="' + barW + '" height="' + h2 + '" class="bar-dept2"><title>' + recent[i].date + ' ' + recent[i].shift + ' 制造二部:' + recent[i].dept2_ach.toFixed(1) + '%</title></rect>';
        
        svg += '<text x="' + (x+barW) + '" y="' + (h+15) + '" class="axis-text" text-anchor="middle" font-size="9">' + recent[i].date + '</text>';
        svg += '<text x="' + (x+barW) + '" y="' + (h+28) + '" class="axis-text" text-anchor="middle" font-size="9">' + recent[i].shift + '</text>';
    }}
    
    // Y轴
    for (var i=0; i<=5; i++) {{
        var y = h - (i/5*h);
        svg += '<text x="-8" y="' + (y+4) + '" class="axis-text" text-anchor="end">' + (i*20) + '%</text>';
    }}
    
    // 图例
    svg += '<rect x="10" y="-14" width="10" height="10" rx="2" class="bar-dept1"/>';
    svg += '<text x="26" y="-5" class="axis-text">制造一部</text>';
    svg += '<rect x="80" y="-14" width="10" height="10" rx="2" class="bar-dept2"/>';
    svg += '<text x="96" y="-5" class="axis-text">制造二部</text>';
    
    svg += '</g></svg>';
    document.getElementById('deptCompareChart').innerHTML = svg;
}}

// ===== 3. 最近3个班次累进曲线 =====
function renderAccum() {{
    // 取最近3个班次
    var lastShifts = shifts.slice(-3);
    if (lastShifts.length === 0) {{ document.getElementById('accumChart').innerHTML = ''; return; }}
    
    // 对每个班次，找到它包含的所有快照记录
    var colors = ['#3498db','#2ecc71','#f39c12','#e74c3c'];
    var ch = makeChart('accumChart', 1300, 320);
    var maxDone = 0;
    
    // 构建每个班次的快照序列
    var shiftSnaps = [];
    for (var s=0; s<lastShifts.length; s++) {{
        var shiftDate = lastShifts[s].date;
        var shiftLabel = lastShifts[s].shift;
        var snaps = [];
        
        // 找到属于这个班次的所有记录
        for (var i=0; i<records.length; i++) {{
            var r = records[i];
            var rShiftDate;
            if (r.shift_group === '夜班' && r.hour < 8) {{
                var d = new Date(r.dt);
                d.setDate(d.getDate() - 1);
                rShiftDate = (d.getMonth()+1).toString().padStart(2,'0') + '/' + d.getDate().toString().padStart(2,'0');
            }} else {{
                rShiftDate = r.date;
            }}
            
            if (rShiftDate === shiftDate && r.shift_group === shiftLabel) {{
                snaps.push(r);
                if (r.total_done > maxDone) maxDone = r.total_done;
            }}
        }}
        shiftSnaps.push({{label:shiftDate+' '+shiftLabel, snaps:snaps, color:colors[s]}});
    }}
    
    if (maxDone === 0) {{ document.getElementById('accumChart').innerHTML = '<p style="color:#556677;text-align:center;padding:60px">暂无产出数据</p>'; return; }}
    maxDone = Math.ceil(maxDone / 50000) * 50000;
    
    var xLabels = ['08:00','10:00','12:00','14:00','16:00','18:00','20:00','22:00','00:00','02:00','04:00','06:00'];
    
    // 找所有班次的时间范围
    var allHours = [];
    for (var s=0; s<shiftSnaps.length; s++) {{
        for (var j=0; j<shiftSnaps[s].snaps.length; j++) {{
            allHours.push(shiftSnaps[s].snaps[j].hour);
        }}
    }}
    var minH = Math.min.apply(null, allHours);
    var maxH = Math.max.apply(null, allHours) + 1;
    var hourRange = maxH - minH;
    
    // 绘制每条线
    for (var s=0; s<shiftSnaps.length; s++) {{
        var snaps = shiftSnaps[s].snaps;
        if (snaps.length === 0) continue;
        
        var path = '', dots = '', area = '';
        for (var j=0; j<snaps.length; j++) {{
            var snapH = snaps[j].hour + snaps[j].dt.substring(14,16)/60; // hour including minutes
            var x = (snapH - minH) / hourRange * ch.w;
            var y = ch.h - (snaps[j].total_done / maxDone * ch.h);
            
            path += (j===0?'M':'L') + x + ',' + y + ' ';
            dots += '<circle cx="' + x + '" cy="' + y + '" r="3" fill="' + shiftSnaps[s].color + '"><title>' + snaps[j].time + ' ' + formatNum(snaps[j].total_done) + '件 (' + snaps[j].total_ach.toFixed(1) + '%)</title></circle>';
        }}
        ch.svg += '<path d="' + path + '" stroke="' + shiftSnaps[s].color + '" stroke-width="2.5" fill="none"/>';
        ch.svg += dots;
    }}
    
    // X 轴
    for (var h=Math.floor(minH/2)*2; h<=maxH; h+=2) {{
        var x = (h - minH) / hourRange * ch.w;
        var label = h.toString().padStart(2,'0') + ':00';
        ch.svg += '<text x="' + x + '" y="' + (ch.h+20) + '" class="axis-text" text-anchor="middle">' + label + '</text>';
    }}
    
    // 图例
    for (var s=0; s<shiftSnaps.length; s++) {{
        ch.svg += '<rect x="' + (10 + s*110) + '" y="-14" width="10" height="10" rx="2" fill="' + shiftSnaps[s].color + '"/>';
        ch.svg += '<text x="' + (26 + s*110) + '" y="-5" class="axis-text">' + shiftSnaps[s].label + '</text>';
    }}
    
    var yLabels = [];
    for (var i=0; i<=5; i++) yLabels.push(formatNum(Math.round(maxDone * i/5)) + '件');
    closeChart(ch, yLabels);
}}

// ===== 4. 班次明细表 =====
function renderTable() {{
    var rows = '';
    var valid = shifts.slice().reverse();
    for (var i=0; i<valid.length; i++) {{
        var s = valid[i];
        var achClass = s.ach >= 30 ? 'color:#2ecc71' : (s.ach >= 15 ? 'color:#f39c12' : 'color:#e74c3c');
        var dept1Tag = s.dept1_ach >= 50 ? 'color:#2ecc71' : (s.dept1_ach >= 25 ? 'color:#f39c12' : 'color:#8899aa');
        var dept2Tag = s.dept2_ach >= 20 ? 'color:#2ecc71' : (s.dept2_ach >= 10 ? 'color:#f39c12' : 'color:#8899aa');
        
        // 进度条
        var barColor = s.ach >= 30 ? '#2ecc71' : (s.ach >= 15 ? '#f39c12' : '#e74c3c');
        var barPct = Math.min(s.ach, 100);
        
        rows += '<tr>' +
            '<td>' + s.date + '</td>' +
            '<td><span class="tag ' + (s.shift==='白班'?'tag-day':'tag-night') + '">' + s.shift + '</span></td>' +
            '<td class="num">' + formatNum(s.plan) + '</td>' +
            '<td class="num" style="color:#fff;font-weight:600">' + formatNum(s.done) + '</td>' +
            '<td class="num" style="' + achClass + ';font-weight:700">' + s.ach.toFixed(1) + '%' +
                '<div class="progress-bar"><div class="progress-fill" style="width:' + barPct + '%;background:' + barColor + '"></div></div></td>' +
            '<td class="num" style="' + dept1Tag + '">' + s.dept1_ach.toFixed(1) + '%</td>' +
            '<td class="num" style="' + dept2Tag + '">' + s.dept2_ach.toFixed(1) + '%</td>' +
            '<td class="num">' + s.active_lines + ' / ' + s.total_lines + '</td>' +
            '<td class="num" style="color:#e74c3c">' + s.idle_lines + '</td>' +
            '</tr>';
    }}
    document.querySelector('#shiftTable tbody').innerHTML = rows;
}}

// ===== 渲染全部 =====
renderKPI();
renderShiftTrend();
renderDeptCompare();
renderAccum();
renderTable();
</script>
</body>
</html>'''

output_path = HTML_DIR / f"当班趋势看板_{now_str}.html"
output_path.write_text(html, encoding='utf-8')
print(f"看板已生成: {output_path}")
print(f"文件大小: {output_path.stat().st_size:,} bytes")

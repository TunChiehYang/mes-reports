#!/usr/bin/env python3
"""异常工时互动查询 — 纯HTML版，无外部依赖"""
import pandas as pd, json, re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC_DIR = Path("/mnt/d/ShareExport/output/V_R_EXCEPTION_HOUR_DETAIL")
files = sorted(SRC_DIR.glob("V_R_EXCEPTION_HOUR_DETAIL_*.csv"), reverse=True)
if not files:
    print("未找到异常工时数据文件")
    exit(1)
SRC = files[0]
print(f"数据源: {SRC.name}")
OUT = Path("/mnt/d/outputHTML")

df = pd.read_csv(SRC, encoding='gbk')
df['TOTAL_CE_TIME'] = pd.to_numeric(df['TOTAL_CE_TIME'], errors='coerce').fillna(0).astype(int)

def parse_date(s):
    s = str(s).strip()
    m = re.match(r'(\d{1,2})-(\d{1,2})月\s*-(\d{2})', s)
    if m: d, mo, y = int(m.group(1)), int(m.group(2)), 2000 + int(m.group(3)); return f"{y}-{mo:02d}-{d:02d}"
    return ''
df['DATE_STR'] = df['WORK_DATE'].apply(parse_date)

def get_dept(line):
    line=str(line).strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$',line): return ("制造一部","冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$',line): return ("制造一部","冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$',line): return ("制造一部","冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$',line): return ("制造二部","清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$',line): return ("制造二部","清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$',line): return ("制造二部","清洗三课")
    return ("未分类","未分类")

PLANNED_CATS = ['其他计划停线', '计划停机', '管理时间']

records = []
for _, r in df.iterrows():
    d, k = get_dept(r['USER_NO'])
    desc = str(r['DESC_CE_LIST']).replace('\\\\n','\n')
    bd = {}
    for part in desc.replace('\\n','\n').split('\n'):
        for item in part.split(','):
            item = item.strip()
            if ':' in item:
                kv = item.split(':', 1)
                try: bd[kv[0].strip()] = int(kv[1].strip())
                except: pass
    unplanned = sum(v for kk, v in bd.items() if kk != '生产' and kk not in PLANNED_CATS)
    records.append({
        'line': r['USER_NO'], 'date': r['DATE_STR'], 'shift': r['SHIFT'],
        'dept': d, 'kes': k, 'total': int(r['TOTAL_CE_TIME']),
        'breakdown': bd, 'unplanned': unplanned,
        'wo': str(r['WO_NOS']) if pd.notna(r['WO_NOS']) else '',
        'model': str(r['MODEL_NOS']) if pd.notna(r['MODEL_NOS']) else '',
    })

lines = sorted(set(r['line'] for r in records))
dates = sorted(set(r['date'] for r in records), reverse=True)
dept_kes = sorted(set(f"{r['dept']}-{r['kes']}" for r in records))

data_json = json.dumps(records, ensure_ascii=False)
lines_json = json.dumps(lines, ensure_ascii=False)
dates_json = json.dumps(dates, ensure_ascii=False)
dept_json = json.dumps(dept_kes, ensure_ascii=False)

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>异常工时互动查询</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333;padding:20px;-webkit-user-select:text;user-select:text}}
.c{{max-width:1400px;margin:0 auto}}
.hd{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:16px 24px;border-radius:12px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center}}
.hd h1{{font-size:20px}}.hd .m{{font-size:12px;opacity:.7}}
.flt{{background:#fff;border-radius:10px;padding:12px 16px;margin-bottom:12px;box-shadow:0 2px 6px rgba(0,0,0,.05);display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.flt label{{font-size:13px;font-weight:600;color:#555}}
.flt select{{padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;font-family:inherit;min-width:110px}}
.btn{{padding:7px 16px;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit}}
.btn-p{{background:#3498db;color:#fff}}.btn-p:hover{{background:#2980b9}}
.btn-r{{background:#fff;color:#e74c3c;border:1px solid #e74c3c}}.btn-r:hover{{background:#fdd}}
.kpi{{display:flex;gap:8px;margin-bottom:12px}}
.kc{{flex:1;background:#fff;border-radius:8px;padding:10px 14px;box-shadow:0 2px 6px rgba(0,0,0,.05);text-align:center}}
.kc .l{{font-size:11px;color:#888}}.kc .v{{font-size:22px;font-weight:700}}.kc .s{{font-size:10px;color:#aaa}}
.row{{display:flex;gap:12px;margin-bottom:12px}}
.col{{flex:1;background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 2px 6px rgba(0,0,0,.05)}}
.col h3{{font-size:14px;margin-bottom:8px;padding-bottom:4px;border-bottom:2px solid #3498db}}
.bar-wrap{{margin:4px 0}}
.bar-label{{display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px}}
.bar-outer{{height:18px;background:#ecf0f1;border-radius:4px;overflow:hidden}}
.bar-inner{{height:100%;border-radius:4px;transition:width .3s;min-width:2px}}
.bar-inner.red{{background:#e74c3c}}.bar-inner.orange{{background:#f39c12}}.bar-inner.blue{{background:#3498db}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f8f9fa;padding:6px 8px;text-align:left;font-weight:600;border-bottom:2px solid #dee2e6;position:sticky;top:0;z-index:1}}
td{{padding:5px 8px;border-bottom:1px solid #f1f3f5}}
tr:hover td{{background:#f8f9ff}}
.n{{text-align:right}}.a{{text-align:right;font-weight:600}}
.tbw{{max-height:500px;overflow-y:auto}}
@media(max-width:900px){{.row{{flex-direction:column}}}}
</style>
</head>
<body>
<div class="c">
<div class="hd"><h1>产线异常工时互动查询</h1><div class="m">{len(records)}条记录 | 排除计划停机 | 实时联动</div></div>

<div class="flt">
<label>部门:</label><select id="fDept" onchange="onDeptChange()"><option value="">全部</option></select>
<label>产线:</label><select id="fLine" onchange="onLineChange()"><option value="">全部</option></select>
<label>机种:</label><select id="fModel"><option value="">全部</option></select>
<label>日期:</label><select id="fDate"><option value="">全部</option></select>
<label>班次:</label><select id="fShift"><option value="">全部</option><option value="白班">白班</option><option value="夜班">夜班</option></select>
<button class="btn btn-p" onclick="apply()">查询</button>
<button class="btn btn-r" onclick="resetAll()">重置</button>
<span style="margin-left:auto;font-size:12px;color:#888" id="info"></span>
</div>

<div class="kpi" id="kpiRow"></div>
<div class="row">
<div class="col"><h3>异常类别分布</h3><div id="catBars"></div></div>
<div class="col"><h3>产线停机 TOP 10</h3><div id="lineBars"></div></div>
</div>
<div class="col"><h3>明细列表</h3><div class="tbw"><table><thead><tr><th>产线</th><th>部门</th><th>日期</th><th>班次</th><th>总工时</th><th>异常类别/时长</th><th>工单</th><th>机型</th></tr></thead><tbody id="tblBody"></tbody></table></div></div>
</div>

<script>
var DATA={data_json};
var LINES={lines_json};
var DATES={dates_json};
var DEPTS={dept_json};
var PLANNED=['其他计划停线','计划停机','管理时间'];

(function(){{
    var d=document.getElementById('fDept');
    d.innerHTML='<option value="">全部</option>'+DEPTS.map(function(x){{return'<option value="'+x+'">'+x+'</option>'}}).join('');
    var l=document.getElementById('fLine');
    l.innerHTML='<option value="">全部</option>'+LINES.map(function(x){{return'<option value="'+x+'">'+x+'</option>'}}).join('');
    var dt=document.getElementById('fDate');
    dt.innerHTML='<option value="">全部</option>'+DATES.map(function(x){{return'<option value="'+x+'">'+x+'</option>'}}).join('');
    apply();
}})();

function onDeptChange(){{
    var fd=document.getElementById('fDept').value;
    var l=document.getElementById('fLine');
    if(fd){{
        var lines=DATA.filter(function(r){{return r.dept+'-'+r.kes===fd}}).map(function(r){{return r.line}});
        lines=[...new Set(lines)].sort();
        l.innerHTML='<option value="">全部</option>'+lines.map(function(x){{return'<option value="'+x+'">'+x+'</option>'}}).join('');
    }}else{{
        l.innerHTML='<option value="">全部</option>'+LINES.map(function(x){{return'<option value="'+x+'">'+x+'</option>'}}).join('');
    }}
    onLineChange();
}}

function onLineChange(){{
    var fl=document.getElementById('fLine').value;
    var m=document.getElementById('fModel');
    var models;
    if(fl){{
        models=DATA.filter(function(r){{return r.line===fl && r.model}}).map(function(r){{return r.model}});
    }}else{{
        models=DATA.filter(function(r){{return r.model}}).map(function(r){{return r.model}});
    }}
    models=[...new Set(models)].sort();
    m.innerHTML='<option value="">全部</option>'+models.map(function(x){{return'<option value="'+x+'">'+x+'</option>'}}).join('');
}}

function apply(){{
    var fd=document.getElementById('fDept').value;
    var fl=document.getElementById('fLine').value;
    var fm=document.getElementById('fModel').value;
    var fdt=document.getElementById('fDate').value;
    var fs=document.getElementById('fShift').value;
    
    var F=DATA.filter(function(r){{
        if(fd && r.dept+'-'+r.kes!==fd) return false;
        if(fl && r.line!==fl) return false;
        if(fm && r.model!==fm) return false;
        if(fdt && r.date!==fdt) return false;
        if(fs && r.shift!==fs) return false;
        return true;
    }});
    
    document.getElementById('info').textContent='匹配 '+F.length+' 条';
    
    // KPI
    var tT=0,pT=0,plT=0,uT=0;
    var catM={{}}, lineM={{}};
    F.forEach(function(r){{
        tT+=r.total;
        for(var k in r.breakdown){{
            var v=r.breakdown[k];
            if(k==='生产') pT+=v;
            else if(PLANNED.indexOf(k)>=0) plT+=v;
            else{{ uT+=v; catM[k]=(catM[k]||0)+v; }}
        }}
        lineM[r.line]=(lineM[r.line]||0);
        for(var k in r.breakdown){{ if(k!=='生产'&&PLANNED.indexOf(k)<0) lineM[r.line]+=r.breakdown[k]; }}
    }});
    
    document.getElementById('kpiRow').innerHTML=
        '<div class="kc"><div class="l">记录</div><div class="v" style="color:#3498db">'+F.length+'</div><div class="s">条</div></div>'+
        '<div class="kc"><div class="l">生产</div><div class="v" style="color:#27ae60">'+(pT/60).toFixed(0)+'h</div><div class="s">'+(tT?(pT/tT*100).toFixed(1):0)+'%</div></div>'+
        '<div class="kc"><div class="l">计划停机</div><div class="v" style="color:#95a5a6">'+(plT/60).toFixed(0)+'h</div><div class="s">'+(tT?(plT/tT*100).toFixed(1):0)+'%</div></div>'+
        '<div class="kc"><div class="l">异常停机</div><div class="v" style="color:#e74c3c">'+(uT/60).toFixed(0)+'h</div><div class="s">'+(tT?(uT/tT*100).toFixed(1):0)+'%</div></div>';
    
    // Category bars
    var cats=Object.entries(catM).sort(function(a,b){{return b[1]-a[1]}}).slice(0,10);
    var maxC=cats.length?cats[0][1]:1;
    var catHtml='';
    cats.forEach(function(c){{
        var pct=c[1]/maxC*100;
        catHtml+='<div class="bar-wrap"><div class="bar-label"><span>'+c[0]+'</span><span>'+(c[1]/60).toFixed(1)+'h</span></div><div class="bar-outer"><div class="bar-inner red" style="width:'+pct+'%"></div></div></div>';
    }});
    if(!catHtml) catHtml='<div style="text-align:center;color:#aaa;padding:20px">无异常数据</div>';
    document.getElementById('catBars').innerHTML=catHtml;
    
    // Line bars
    var lines=Object.entries(lineM).sort(function(a,b){{return b[1]-a[1]}}).slice(0,10);
    var maxL=lines.length?lines[0][1]:1;
    var lineHtml='';
    lines.forEach(function(l){{
        var pct=l[1]/maxL*100;
        lineHtml+='<div class="bar-wrap"><div class="bar-label"><span>'+l[0]+'</span><span>'+(l[1]/60).toFixed(1)+'h</span></div><div class="bar-outer"><div class="bar-inner orange" style="width:'+pct+'%"></div></div></div>';
    }});
    if(!lineHtml) lineHtml='<div style="text-align:center;color:#aaa;padding:20px">无停机数据</div>';
    document.getElementById('lineBars').innerHTML=lineHtml;
    
    // Table
    var tbody='';
    F.sort(function(a,b){{return b.total-a.total}}).forEach(function(r){{
        var bd=[];
        for(var k in r.breakdown){{ if(k!=='生产'&&PLANNED.indexOf(k)<0) bd.push(k+':'+r.breakdown[k]+'min'); }}
        tbody+='<tr><td>'+r.line+'</td><td>'+r.dept+'-'+r.kes+'</td><td>'+r.date+'</td><td>'+r.shift+'</td><td class="n">'+r.total+'min</td><td style="font-size:11px">'+(bd.join(', ')||'-')+'</td><td style="font-size:11px">'+r.wo+'</td><td style="font-size:11px">'+r.model+'</td></tr>';
    }});
    document.getElementById('tblBody').innerHTML=tbody||'<tr><td colspan="8" style="text-align:center;color:#aaa;padding:30px">无匹配数据</td></tr>';
}}

function resetAll(){{
    document.getElementById('fDept').value=''; onDeptChange();
    document.getElementById('fLine').value=''; onLineChange();
    document.getElementById('fModel').value='';
    document.getElementById('fDate').value='';
    document.getElementById('fShift').value='';
    apply();
}}
</script>
</body>
</html>'''

nm = "异常工时查询.html"
op = OUT / nm
op.write_text(html, encoding='utf-8')
print(f"✅ {op} ({op.stat().st_size/1024:.0f} KB)")
print(f"   http://192.168.101.152:8080/{nm}")
import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])

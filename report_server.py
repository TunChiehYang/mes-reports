#!/usr/bin/env python3
"""
MES 生产数据分析平台 Web 服务器
端口 8080，服务 D:\outputHTML 目录
首页按类型分四区：生产日报 · 月计划分析 · 当班分析 · 生产周报
"""

import http.server
import os
import socket
import socketserver
from datetime import datetime
from pathlib import Path
import urllib.parse
import json

HTML_DIR = Path("/mnt/d/outputHTML")
COUNTER_FILE = Path("/tmp/hermes_web_counter.txt")
PORT = 8080

# ====== 首页 HTML/CSS/JS ======
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MES 生产数据分析平台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Microsoft YaHei','WenQuanYi Zen Hei',sans-serif;background:#f0f2f5;color:#333;min-height:100vh;-webkit-user-select:text;user-select:text}
.topbar{background:linear-gradient(135deg,#1a1a2e,#16213e 50%,#0f3460);color:#fff;padding:18px 24px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.15)}
.topbar h1{font-size:22px;margin-bottom:2px}
.topbar .sub{font-size:12px;opacity:.75}
.main{max-width:1100px;margin:0 auto;padding:20px}
.filter-bar{background:#fff;border-radius:10px;padding:12px 20px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.06);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.filter-bar label{font-size:14px;font-weight:600;color:#2c3e50;white-space:nowrap}
.filter-bar input[type=date]{padding:8px 12px;border:2px solid #ddd;border-radius:8px;font-size:14px;font-family:inherit;outline:none}
.filter-bar input[type=date]:focus{border-color:#3498db}
.btn{padding:8px 16px;border:none;border-radius:8px;font-size:13px;cursor:pointer;font-family:inherit;transition:all .2s}
.btn-primary{background:#3498db;color:#fff}.btn-primary:hover{background:#2980b9}
.btn-outline{background:#fff;color:#3498db;border:2px solid #3498db}.btn-outline:hover{background:#ebf5fb}
.filter-info{font-size:13px;color:#7f8c8d;margin-left:auto}
.quick-dates{display:flex;gap:6px;flex-wrap:wrap}
.quick-date{padding:4px 10px;border-radius:12px;font-size:12px;cursor:pointer;background:#f0f4ff;color:#3498db;border:1px solid #d5e4fb;white-space:nowrap}
.quick-date:hover{background:#3498db;color:#fff}
.sections{display:flex;flex-direction:column;gap:20px}
.category{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.06)}
.cat-header{padding:14px 22px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #eee}
.cat-header .icon{font-size:26px}
.cat-header .title{font-size:16px;font-weight:700}
.cat-header .count{font-size:12px;color:#888;margin-left:auto}
.cat-daily .cat-header{background:linear-gradient(135deg,#ebf5fb,#d6eaf8)}
.cat-monthly .cat-header{background:linear-gradient(135deg,#fdedec,#fadbd8)}
.cat-shift .cat-header{background:linear-gradient(135deg,#e8f8f5,#d1f2eb)}
.cat-exception .cat-header{background:linear-gradient(135deg,#fef3e2,#fde2c3)}
.cat-query .cat-header{background:linear-gradient(135deg,#eaf2f8,#d4e6f1)}
.cat-gap .cat-header{background:linear-gradient(135deg,#fdebd0,#f5cba7)}
.cat-weekly .cat-header{background:linear-gradient(135deg,#fef9e7,#fdebd0)}
.file-item{display:flex;align-items:center;padding:10px 22px;text-decoration:none;color:#2c3e50;border-bottom:1px solid #f5f5f5;transition:background .15s}
.file-item:last-child{border-bottom:none}
.file-item:hover{background:#f8f9ff}
.file-item.hidden{display:none}
.file-icon{font-size:20px;margin-right:12px;flex-shrink:0}
.file-info{flex:1;min-width:0}
.file-name{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-meta{font-size:11px;color:#95a5a6;margin-top:2px}
.file-size{font-size:12px;color:#7f8c8d;white-space:nowrap;margin-left:10px}
.time-badge{display:inline-block;padding:1px 7px;border-radius:8px;font-size:10px;font-weight:600;margin-left:6px}
.time-badge.day{background:#fef3c7;color:#b45309}
.time-badge.night{background:#e0e7ff;color:#3730a3}
.empty-state{text-align:center;padding:36px 20px;color:#bdc3c7}
.empty-state .icon{font-size:32px;margin-bottom:6px}
.footer{text-align:center;padding:16px;color:#888;font-size:12px;margin-top:10px}
@media(max-width:768px){.main{padding:10px}.filter-bar{flex-direction:column;align-items:flex-start}}
</style>
</head>
<body>
<div class="topbar">
<h1>MES 生产数据分析平台</h1>
<div class="sub">生产日报 · 月计划分析 · 当班分析 · 异常工时 · 生产周报</div>
</div>
<div class="main">
<div class="filter-bar">
<label>日期筛选：</label>
<input type="date" id="datePicker">
<button class="btn btn-primary" onclick="filterByDate()">筛选</button>
<button class="btn btn-outline" onclick="showAll()">显示全部</button>
<div class="quick-dates" id="quickDates"></div>
<span class="filter-info" id="filterInfo"></span>
</div>
<div class="sections">

<div class="category cat-shift">
<div class="cat-header"><span class="icon">&#x1F3ED;</span><span class="title">当班生产分析</span><span class="count" id="cnt-shift">—</span></div>
<div class="file-list" id="list-shift"></div>
</div>

<div class="category cat-exception">
<div class="cat-header"><span class="icon">&#x26A0;</span><span class="title">异常工时分析</span><span class="count" id="cnt-exception">—</span></div>
<div class="file-list" id="list-exception"></div>
</div>

<div class="category cat-query">
<div class="cat-header"><span class="icon">&#x1F50D;</span><span class="title">异常工时动态查询</span><span class="count" id="cnt-query">—</span></div>
<div class="file-list" id="list-query"></div>
</div>

<div class="category cat-gap">
<div class="cat-header"><span class="icon">&#x1F4E6;</span><span class="title">出货缺口推估</span><span class="count" id="cnt-gap">—</span></div>
<div class="file-list" id="list-gap"></div>
</div>

<div class="category cat-daily">
<div class="cat-header"><span class="icon">&#x1F4CA;</span><span class="title">生产日报</span><span class="count" id="cnt-daily">—</span></div>
<div class="file-list" id="list-daily"></div>
</div>

<div class="category cat-weekly">
<div class="cat-header"><span class="icon">&#x1F4C8;</span><span class="title">生产周报</span><span class="count" id="cnt-weekly">—</span></div>
<div class="file-list" id="list-weekly"></div>
</div>

<div class="category cat-monthly">
<div class="cat-header"><span class="icon">&#x1F4CB;</span><span class="title">月计划分析</span><span class="count" id="cnt-monthly">—</span></div>
<div class="file-list" id="list-monthly"></div>
</div>

</div>
</div>
<script>
var allFiles = __FILES_JSON__;

function getType(n){
    if(n.startsWith('生产日报'))return'daily';
    if(n.startsWith('月计划分析'))return'monthly';
    if(n.startsWith('当班分析'))return'shift';
    if(n.startsWith('异常工时分析'))return'exception';
    if(n.startsWith('异常工时查询'))return'query';
    if(n.startsWith('每日缺口'))return'gap';
    if(n.startsWith('生产周报'))return'weekly';
    return'other';
}
function getIcon(t){return{daily:'&#x1F4C4;',monthly:'&#x1F4CB;',shift:'&#x1F3ED;',exception:'&#x26A0;',query:'&#x1F50D;',gap:'&#x1F4E6;',weekly:'&#x1F4C8;'}[t]||'&#x1F4CE;';}
function parseInfo(n){
    var p=n.replace('.html','').split('_'),d='',t='';
    for(var i=p.length-1;i>=0;i--){if(/^\d{8}$/.test(p[i])){d=p[i];break}}
    if(d){var idx=p.indexOf(d);if(idx>=0&&idx+1<p.length&&/^\d{4}$/.test(p[idx+1]))t=p[idx+1]}
    var dd=d.length===8?d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6,8):'';
    var tt=t.length===4?t.slice(0,2)+':'+t.slice(2,4):'';
    return{date:d,time:t,displayDate:dd,displayTime:tt};
}
function isNight(t){if(t.length!==4)return false;var h=parseInt(t.slice(0,2));return h<8||h>=20;}

function buildItem(f){
    var info=parseInfo(f.name),type=getType(f.name),icon=getIcon(type);
    var night=isNight(info.time);
    var badge=info.time?'<span class="time-badge '+(night?'night':'day')+'">'+(night?'夜班':'白班')+'</span>':'';
    var html='<a class="file-item" data-date="'+info.date+'" data-type="'+type+'" data-nodate="'+(!info.date)+'" href="/'+encodeURIComponent(f.name)+'">';
    html+='<span class="file-icon">'+icon+'</span>';
    html+='<span class="file-info">';
    html+='<span class="file-name">'+f.name+badge+'</span>';
    html+='<span class="file-meta">'+info.displayDate+' '+info.displayTime+' &middot; '+f.mtime+'</span>';
    html+='</span>';
    html+='<span class="file-size">'+f.size+'</span>';
    html+='</a>';
    return html;
}

function renderAll(){
    var ct={daily:'list-daily',monthly:'list-monthly',shift:'list-shift',exception:'list-exception',query:'list-query',gap:'list-gap',weekly:'list-weekly'};
    var cnt={};
    for(var k in ct){document.getElementById(ct[k]).innerHTML='';cnt[k]=0;}
    allFiles.forEach(function(f){
        var type=getType(f.name),cid=ct[type]||ct['daily'];
        var el=document.getElementById(cid);
        if(el){el.innerHTML+=buildItem(f);cnt[type]=(cnt[type]||0)+1;}
    });
    document.getElementById('cnt-daily').textContent=cnt['daily']+' 份';
    document.getElementById('cnt-monthly').textContent=cnt['monthly']+' 份';
    document.getElementById('cnt-shift').textContent=cnt['shift']+' 份';
    document.getElementById('cnt-exception').textContent=cnt['exception']+' 份';
    document.getElementById('cnt-query').textContent=cnt['query']+' 份';
    document.getElementById('cnt-gap').textContent=cnt['gap']+' 份';
    document.getElementById('cnt-weekly').textContent=cnt['weekly']+' 份';
    // quick dates
    var dates={};
    allFiles.forEach(function(f){var d=parseInfo(f.name).date;if(d)dates[d]=1;});
    var sd=Object.keys(dates).sort().reverse().slice(0,7);
    var qh='';
    sd.forEach(function(d){qh+='<span class="quick-date" onclick="quickFilter(\''+d+'\')">'+d.slice(4,6)+'/'+d.slice(6,8)+'</span>';});
    document.getElementById('quickDates').innerHTML=qh;
}

function filterByDate(){
    var sel=document.getElementById('datePicker').value;
    if(!sel)return;
    var tgt=sel.replace(/-/g,''),vis=0;
    document.querySelectorAll('.file-item').forEach(function(el){
        if(el.getAttribute('data-nodate')==='true'){el.classList.remove('hidden');return;}
        if(el.getAttribute('data-date')===tgt){el.classList.remove('hidden');vis++;}
        else{el.classList.add('hidden');}
    });
    var info=document.getElementById('filterInfo');
    info.textContent=vis>0?'找到 '+vis+' 份报告':'该日期暂无报告';
    info.style.color=vis>0?'#27ae60':'#e74c3c';
}
function quickFilter(d){
    document.getElementById('datePicker').value=d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6,8);
    filterByDate();
}
function showAll(){
    document.getElementById('datePicker').value='';
    document.getElementById('filterInfo').textContent='';
    document.querySelectorAll('.file-item').forEach(function(el){el.classList.remove('hidden');});
}
renderAll();
(function(){
    var t=new Date();
    document.getElementById('datePicker').value=t.getFullYear()+'-'+String(t.getMonth()+1).padStart(2,'0')+'-'+String(t.getDate()).padStart(2,'0');
    filterByDate();
})();
</script>
<div class="footer">累计访问：__COUNTER__ 次 | MES 生产数据分析平台</div>
</body>
</html>"""


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HTML_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/' or path == '/index.html':
            files_json = []
            if HTML_DIR.exists():
                for f in sorted(HTML_DIR.glob('*.html'), reverse=True):
                    stat = f.stat()
                    fname = f.name
                    parts = fname.replace('.html', '').split('_')
                    date_str = ''
                    for p in parts:
                        if len(p) == 8 and p.isdigit():
                            date_str = p
                            break
                    files_json.append({
                        'name': fname,
                        'size': f'{stat.st_size/1024:.0f} KB',
                        'mtime': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                        'date': date_str,
                    })

            # 访问计数
            count = 1
            if COUNTER_FILE.exists():
                count = int(COUNTER_FILE.read_text().strip()) + 1
            COUNTER_FILE.write_text(str(count))

            body = INDEX_HTML.replace(
                '__FILES_JSON__', json.dumps(files_json, ensure_ascii=False)
            ).replace('__COUNTER__', str(count)).encode('utf-8')

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
    timeout = 30  # 30 秒超时，防止客户端挂起阻塞整个服务
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


def main():
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(str(HTML_DIR))
    with ReuseTCPServer(("0.0.0.0", PORT), ReportHandler) as httpd:
        print(f"MES 平台已启动: http://localhost:{PORT}")
        print(f"内网: http://192.168.101.152:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n服务已停止")


if __name__ == '__main__':
    main()

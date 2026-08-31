#!/usr/bin/env python3
"""
当班生产情况 — PG 数据源版（第二阶段）
每两小时从 PG 10.2.20.127 读取 GET_VALID_WOW 同步的工单级数据（v_plan_actual_current），
生成当班分析报告 + 推送邮件。不再依赖 b-mes 邮件解析。
"""
import re, smtplib, io, base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# ============ 中文字体 ============
FONT_CANDIDATES = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei', 'Microsoft YaHei']
for fname in FONT_CANDIDATES:
    if fname in {f.name for f in fm.fontManager.ttflist}:
        plt.rcParams['font.family'] = fname
        break
plt.rcParams['axes.unicode_minus'] = False

# ============ 配置 ============
SMTP_HOST = "192.168.0.188"   # 内网邮件服务器（公网域名对10.2.20.x受限）
SMTP_PORT = 465
USERNAME = "b-mes"
PASSWORD = "gmo@1001"
SENDER = "b-mes@chiachang.com"
SENDER_NAME = "MES系统"

OUTPUT_DIR = Path("/mnt/d/outputHTML")
REPORT_URL_BASE = "http://10.2.20.127:8080"

# ============ PG 历史数据（班序计算） ============
PG = dict(host='10.2.20.127', port=5432, user='postgres',
          password='Chia@1234', dbname='mes_plan')

RECIPIENTS = [
    ("prima.yang@chiachang.com", "MES经理"),
    ("meng.wang@chiachang.com", ""),
    ("xiuli.nie@chiachang.com", "IE课长"),
    ("ryan.lai@chiachang.com", "制造一部经理"),
    ("houlin.song@chiachang.com", "制一部课长"),
    ("yongjun.chen@chiachang.com", "制一部课长"),
    ("jian.zhang@chiachang.com", "制一部课长"),
    ("zhiyong.wang@chiachang.com", "生管课长"),
    ("rongrong.guo@chiachang.com", "生管"),
    ("chuang.fang@chiachang.com", "生管"),
    ("mingxing.wang@chiachang.com", "生管"),
    ("linfan.zhang@chiachang.com", "制造二部经理"),
    ("suhua.fan@chiachang.com", "制二部课长"),
    ("hongliang.li@chiachang.com", "制二部课长"),
    ("guangyin.li@chiachang.com", "制二部课长"),
    ("b-mfg210@chiachang.com", "制二统计"),
    ("yaya.fan@chiachang.com", "制一统计"),
    ("l.c.cheng@chiachang.com", "总经理"),
]

# ============ 部门分类 ============
def get_dept(line):
    line = line.strip().upper()
    if re.match(r'^NA0[1-9]$|^NA(19|20|21)$|^NB0[1-5]$|^NB26$', line):
        return ("制造一部", "冲压一课")
    if re.match(r'^NA1[0-8]$|^NB0[6-9]$|^NB10$', line):
        return ("制造一部", "冲压二课")
    if re.match(r'^NA(2[3-9]|3[0-2])$|^NB(1[1-9]|2[0-5])$', line):
        return ("制造一部", "冲压三课")
    if re.match(r'^NQ(10[1-9]|11[0-5])$|^NQ(30[1-9]|310)$', line):
        return ("制造二部", "清洗一课")
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$', line):
        return ("制造二部", "清洗二课")
    if re.match(r'^NQ(40[1-9]|41[0-2])$|^NQ(50[1-9]|51[0-2])$', line):
        return ("制造二部", "清洗三课")
    return ("未分类", "未分类")


def get_latest_shift_data():
    """从 PG 读取最新同步的当班生产数据（v_plan_actual_current）
    返回 (records, sync_time)
    records: 工单级记录列表（字段与邮件版兼容）
    sync_time: 数据同步时间
    """
    try:
        conn = psycopg2.connect(**PG)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 最新同步时间
        cur.execute("SELECT MAX(sync_time) as st FROM v_plan_actual_current")
        sync_time = cur.fetchone()['st']
        if sync_time is None:
            print("  ⚠ v_plan_actual_current 无数据（Oracle 同步未运行？）")
            return None, None
        # 取该同步时间的全部数据
        cur.execute("""
            SELECT * FROM v_plan_actual_current WHERE sync_time = %s
        """, (sync_time,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  ⚠ PG 读取失败: {e}")
        return None, None

    # 转换为与邮件版兼容的记录格式
    # 关键：GET_VALID_WOW 每工单有白班+夜班两行，只保留当前班次的行
    # 班次判定：先看数据里有哪些班次，再结合同步时间选当前班次
    cur_shift = "白班" if 8 <= sync_time.hour < 20 else "夜班"
    # 数据里实际存在的班次
    avail_shifts = {r['clas_type'] for r in rows if r['clas_type']}
    if avail_shifts and cur_shift not in avail_shifts:
        # 若当前班次数据尚未同步（如周末/换班），回退到数据里的班次
        cur_shift = sorted(avail_shifts)[0]
    records = []
    for r in rows:
        if not r['wo_id']:
            continue  # 跳过无工单行（无计划）
        if r['clas_type'] != cur_shift:
            continue  # 只统计当前班次
        ach = (r['actual_qty'] / r['wo_plan_qty'] * 100) if r['wo_plan_qty'] else 0
        records.append({
            'line': r['line_id'],
            'wo_id': r['wo_id'],
            'part_no': r['part_no'] or '',
            'model': (r['model_no'] or '')[:60],
            'wo_total': r['total_qty'] or 0,        # 工单总数量
            'wo_done': r['output_qty'] or 0,        # 工单累计完成
            'shift_plan': r['wo_plan_qty'] or 0,    # 当班计划
            'shift_done': r['actual_qty'] or 0,     # 当班实际
            'ach': ach,
            'reason': r['reason'] or '',
            'tplan_start': r['tplan_start'],
            'clas_type': r['clas_type'],
            'capacit': r['capacit'] or 0,           # 标准产能
            'std_manpower': r['standard_manpower'] or 0,  # 标准人力
            'partner': r['partner_name'] or '',     # 客户
            'partner_code': r['partner_code'] or '',
            'direct_wash': r['direct_wash'] or '',  # 直通/非直通
        })
    return records, sync_time


def calc_shift_seq_pg(records, sync_time):
    """计算每个工单当前是第几个班生产（开始有产出=第1班）+ 进度偏差
    历史数据源（合并两个表）：
      - plan_actual_detail（8/12~8/22 CSV 导入的历史快照）
      - plan_actual_hourly（8/25 起每小时 Oracle 同步）
    班次键 = (tplan_start, clas_type)，每班取最后一次快照的 output_qty/wo_plan_qty
    sync_time: 当前数据同步时间（datetime），用于确定"当前班次"
    返回 { (line_id, wo_id): {'nth':n, 'plan_sum':p, 'done':d, 'diff':x, 'diff_pct':y} }
    """
    if not records:
        return {}
    try:
        conn = psycopg2.connect(**PG)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 当前工单集合
        wanted = {(r['line'], r['wo_id']) for r in records}
        # 1. plan_actual_detail 历史（8/12~8/22，tplan_start 推班次）
        cur.execute("""
            SELECT line_id, wo_id, tplan_start, clas_type, total_qty, output_qty, wo_plan_qty
            FROM plan_actual_detail
            WHERE wo_id IS NOT NULL AND wo_id != ''
              AND tplan_start IS NOT NULL
        """)
        rows1 = cur.fetchall()
        # 2. plan_actual_hourly 当前积累（tplan_start 推班次）
        cur.execute("""
            SELECT line_id, wo_id, tplan_start, clas_type, total_qty, output_qty, wo_plan_qty,
                   sync_time
            FROM plan_actual_hourly
            WHERE wo_id IS NOT NULL AND wo_id != ''
              AND tplan_start IS NOT NULL
              AND sync_time <= %s
        """, (sync_time,))
        rows2 = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"  ⚠ 班序计算失败: {e}")
        return {}

    # 合并：班次键 = (tplan_start, clas_type)，同班次多条取 sync_time 最新
    from collections import OrderedDict
    groups = OrderedDict()   # (line, wo) -> {班次键: (output_qty, wo_plan_qty, total_qty, sync_time)}

    def parse_ora_date(s):
        """解析 Oracle 格式日期 '08-8月 -26' → date(2026-08-08)"""
        if s is None:
            return None
        if isinstance(s, (datetime,)):
            return s.date()
        try:
            # 格式: DD-MM月 -YY
            import re as _re
            m = _re.match(r'(\d{1,2})-(\d{1,2})月\s*-?(\d{2,4})', str(s).strip())
            if m:
                dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
                yy = 2000 + yy if yy < 100 else yy
                return datetime(yy, mm, dd).date()
        except Exception:
            pass
        try:
            from datetime import date as _date
            return _date.fromisoformat(str(s)[:10])
        except Exception:
            return None

    def add_row(r, order_ts):
        key = (r['line_id'], r['wo_id'])
        if key not in wanted:
            return
        d = parse_ora_date(r['tplan_start'])
        if d is None:
            return
        sk = (d, r['clas_type'])
        g = groups.setdefault(key, OrderedDict())
        if sk not in g or (order_ts is not None and (g[sk][3] is None or order_ts > g[sk][3])):
            g[sk] = (r['output_qty'] or 0, r['wo_plan_qty'] or 0, r['total_qty'] or 0, order_ts)

    for r in rows1:
        add_row(r, None)   # plan_actual_detail 无 sync_time，仅首次加入
    for r in rows2:
        add_row(r, r['sync_time'])

    # 当前班次 = 最新数据里的 (tplan_start, clas_type)
    cur_shift = None
    for r in records:
        d = parse_ora_date(r.get('tplan_start'))
        if d and r.get('clas_type'):
            cur_shift = (d, r['clas_type'])
            break

    result = {}
    for key, shifts in groups.items():
        # 班次按时间排序（日期 + 白班在前）
        sorted_shifts = sorted(shifts.items(),
                               key=lambda kv: (kv[0][0], 0 if kv[0][1] == '白班' else 1))
        # 首次有产出班次
        first_idx = None
        for i, (sk, (done, plan, tot, ts)) in enumerate(sorted_shifts):
            if done > 0:
                first_idx = i
                break
        if first_idx is None:
            continue  # 从未有产出
        # 当前班次序号
        cur_idx = None
        for i, (sk, _) in enumerate(sorted_shifts):
            if sk == cur_shift:
                cur_idx = i
                break
        if cur_idx is None:
            cur_idx = len(sorted_shifts) - 1
        # 评估基准：当班之前的一班（当前班次数据不完整，先不算）
        eval_idx = cur_idx - 1
        if eval_idx < first_idx or eval_idx < 0:
            continue  # 当班之前还没有完整班次，无法评估进度
        nth = eval_idx - first_idx + 1
        # 累计计划（从首次产出班到评估班）与实际完成
        # 约束：累计计划不能超过工单总数量（wo_total）
        wo_total = shifts[sorted_shifts[eval_idx][0]][2]
        plan_sum = sum(shifts[sk][1] for sk, _ in sorted_shifts[first_idx:eval_idx + 1])
        if wo_total and wo_total > 0:
            plan_sum = min(plan_sum, wo_total)
        done = shifts[sorted_shifts[eval_idx][0]][0]
        diff = plan_sum - done  # >0 = 落后
        diff_pct = diff / plan_sum * 100 if plan_sum else 0
        result[key] = {'nth': nth, 'plan_sum': plan_sum, 'done': done,
                       'diff': diff, 'diff_pct': diff_pct}
    return result


def analyze(records, date_str, date_label_override=None, shift_override=None):
    """分析产线数据，返回报告文本"""
    total_shift_plan = sum(r['shift_plan'] for r in records)
    total_shift_done = sum(r['shift_done'] for r in records)
    total_ach = total_shift_done / total_shift_plan * 100 if total_shift_plan else 0

    # 部门汇总（排除当班完成数为0的产线，不拖累达成率）
    dept_data = defaultdict(lambda: {'plan': 0, 'done': 0, 'lines': 0, 'active_lines': 0})
    for r in records:
        dept, kes = get_dept(r['line'])
        key = f"{dept}-{kes}"
        dept_data[key]['lines'] += 1
        if r['shift_done'] > 0:
            dept_data[key]['plan'] += r['shift_plan']
            dept_data[key]['done'] += r['shift_done']
            dept_data[key]['active_lines'] += 1

    # Top/Bottom
    sorted_ach = sorted(records, key=lambda x: x['ach'], reverse=True)
    top5 = [r for r in sorted_ach if r['shift_plan'] > 0][:5]
    zero_lines = [r for r in records if r['ach'] == 0 and r['shift_plan'] > 0]

    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}

    # 判断班次（生产日期+班次由 main 传入覆盖）
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        shift = "白班" if 8 <= dt.hour < 20 else "夜班"
        date_label = dt.strftime("%m/%d %H:%M")
    except:
        shift = ""
        date_label = date_str
    if shift_override:
        shift = shift_override
    if date_label_override:
        date_label = date_label_override

    # 制造一部/二部分别统计
    d1_plan = sum(r['shift_plan'] for r in records if r['line'].startswith(('NA','NB')))
    d1_done = sum(r['shift_done'] for r in records if r['line'].startswith(('NA','NB')))
    d1_ach = d1_done / d1_plan * 100 if d1_plan else 0
    d2_plan = sum(r['shift_plan'] for r in records if r['line'].startswith('NQ'))
    d2_done = sum(r['shift_done'] for r in records if r['line'].startswith('NQ'))
    d2_ach = d2_done / d2_plan * 100 if d2_plan else 0

    report = f"""当班生产情况分析 ({shift})
{'='*50}
邮件时间: {date_label}
解析产线: {len(records)} 条
{'='*50}

【总体概况】
  全厂计划: {total_shift_plan:,} 件 | 完成: {total_shift_done:,} 件 | 达成率: {total_ach:.1f}%

  制造一部(冲压): 计划 {d1_plan:,} | 完成 {d1_done:,} | 达成率 {d1_ach:.1f}%
  制造二部(清洗): 计划 {d2_plan:,} | 完成 {d2_done:,} | 达成率 {d2_ach:.1f}%

【部门达成率】
"""
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['lines'] > 0:
                ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
                bar = '█' * int(ach / 5) + '░' * (20 - int(ach / 5))
                note = f"({d['active_lines']}/{d['lines']}线有产出)" if d['active_lines'] < d['lines'] else f"({d['lines']}线)"
                report += f"  {dept} {kes:<8} {bar} {ach:>5.1f}%  {note}\n"

    report += "\n【达成率 TOP 5】\n"
    for i, r in enumerate(top5, 1):
        report += f"  {i}. {r['line']:<6} {r['model'][:28]:<30} 计划{r['shift_plan']:>6,} → 完成{r['shift_done']:>6,}  {r['ach']:>5.1f}%\n"

    if zero_lines:
        report += f"\n【未开动产线】{len(zero_lines)} 条计划未动\n"
        for r in zero_lines[:5]:
            report += f"  {r['line']:<6} {r['model'][:30]:<32} 计划{r['shift_plan']:>6,}\n"
        if len(zero_lines) > 5:
            report += f"  ... 还有 {len(zero_lines)-5} 条\n"

    # 进度落后警示（班序 × 累计计划 vs 实际完成）
    lag_list = [r for r in records
                if r.get('diff') is not None and r['diff'] > 0
                and not (r['wo_total'] > 0 and r['wo_done'] >= r['wo_total'])]
    lag_list.sort(key=lambda x: x['diff'], reverse=True)
    if lag_list:
        report += f"\n🚨【进度落后警示】{len(lag_list)} 条产线未跟上计划（累计计划>实际完成）\n"
        for r in lag_list[:8]:
            report += (f"  {r['line']:<6} {r['model'][:20]:<22} {r['wo_id'][:20]:<22} "
                       f"计划{r['plan_sum']:>8,} → 完成{r['wo_done']:>8,} "
                       f"落后-{r['diff']:>8,} (-{r['diff_pct']:.0f}%) 第{r['nth_shift']}班\n")
        if len(lag_list) > 8:
            report += f"  ... 共 {len(lag_list)} 条\n"

    report += f"\n📎 {REPORT_URL_BASE}/ | MES自动分析 {datetime.now().strftime('%m/%d %H:%M')}"
    return report, shift, date_label, dept_data, top5, zero_lines, total_shift_plan, total_shift_done, total_ach


def fig_to_base64(fig):
    """matplotlib figure → base64 PNG"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64


def chart_dept_ach(dept_data):
    """部门达成率柱状图"""
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    
    labels = []
    ach_vals = []
    plan_vals = []
    done_vals = []
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['lines'] > 0:
                labels.append(f"{kes}")
                ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
                ach_vals.append(ach)
                plan_vals.append(d['plan'])
                done_vals.append(d['done'])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Left: Achievement rate
    colors = ['#e74c3c' if a < 30 else '#f39c12' if a < 60 else '#27ae60' for a in ach_vals]
    bars = ax1.barh(range(len(labels)), ach_vals, color=colors, edgecolor='white')
    for bar, ach in zip(bars, ach_vals):
        ax1.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2, f'{ach:.1f}%', 
                va='center', fontsize=10, fontweight='bold')
    ax1.set_yticks(range(len(labels)))
    ax1.set_yticklabels(labels, fontsize=10)
    ax1.set_title('部门达成率', fontsize=13, fontweight='bold')
    ax1.set_xlim(0, max(ach_vals) * 1.3 if max(ach_vals) > 0 else 100)
    ax1.grid(axis='x', alpha=0.3)
    ax1.invert_yaxis()

    # Right: Plan vs Done
    x = np.arange(len(labels))
    w = 0.35
    ax2.barh(x + w/2, plan_vals, w, label='计划量', color='#3498db', alpha=0.85)
    ax2.barh(x - w/2, done_vals, w, label='完成量', color='#27ae60', alpha=0.85)
    ax2.set_yticks(x)
    ax2.set_yticklabels(labels, fontsize=10)
    ax2.set_title('计划 vs 完成', fontsize=13, fontweight='bold')
    ax2.legend(fontsize=9, loc='lower right')
    ax2.grid(axis='x', alpha=0.3)
    ax2.invert_yaxis()

    fig.tight_layout()
    return fig_to_base64(fig)


def chart_partner_top(records):
    """客户产出排行 TOP10"""
    from collections import defaultdict
    agg = defaultdict(lambda: {'plan': 0, 'done': 0, 'wos': 0})
    for r in records:
        p = r.get('partner') or '未标注'
        agg[p]['plan'] += r['shift_plan']
        agg[p]['done'] += r['shift_done']
        agg[p]['wos'] += 1
    items = sorted(agg.items(), key=lambda x: -x[1]['done'])[:10]
    if not items:
        return None
    labels = [k for k, _ in items]
    done = [v['done'] for _, v in items]
    plan = [v['plan'] for _, v in items]
    wos = [v['wos'] for _, v in items]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    # 左：产出横向条形
    colors = ['#3498db'] * len(labels)
    bars = ax1.barh(range(len(labels)), done, color=colors, edgecolor='white')
    for bar, v in zip(bars, done):
        ax1.text(bar.get_width() + 300, bar.get_y() + bar.get_height()/2,
                 f'{v:,}', va='center', fontsize=10, fontweight='bold')
    ax1.set_yticks(range(len(labels)))
    ax1.set_yticklabels(labels, fontsize=10)
    ax1.set_title('客户当班产出 TOP10', fontsize=13, fontweight='bold')
    ax1.grid(axis='x', alpha=0.3)
    ax1.invert_yaxis()
    # 右：达成率
    ach = [v / p * 100 if p else 0 for v, p in zip(done, plan)]
    colors2 = ['#e74c3c' if a < 30 else '#f39c12' if a < 60 else '#27ae60' for a in ach]
    bars2 = ax2.barh(range(len(labels)), ach, color=colors2, edgecolor='white')
    for bar, a in zip(bars2, ach):
        ax2.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                 f'{a:.1f}%', va='center', fontsize=10, fontweight='bold')
    ax2.set_yticks(range(len(labels)))
    ax2.set_yticklabels(labels, fontsize=10)
    ax2.set_title('客户达成率', fontsize=13, fontweight='bold')
    ax2.grid(axis='x', alpha=0.3)
    ax2.invert_yaxis()
    fig.tight_layout()
    return fig_to_base64(fig)


def chart_wo_progress(records):
    """工单进度分布饼图：按部门分左右（制造一部/制造二部）"""
    DEPTS = ["制造一部", "制造二部"]

    def _calc(dept_recs):
        done_cnt = sum(1 for r in dept_recs if r['wo_total'] > 0 and r['wo_done'] >= r['wo_total'])
        active_cnt = sum(1 for r in dept_recs if 0 < r['wo_done'] < r['wo_total'])
        idle_cnt = sum(1 for r in dept_recs if r['wo_done'] == 0)
        return done_cnt, active_cnt, idle_cnt

    # 过滤各部门记录
    dept_recs = {d: [r for r in records if get_dept(r['line'])[0] == d] for d in DEPTS}
    if sum(sum(_calc(dept_recs[d])) for d in DEPTS) == 0:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    colors = ['#27ae60', '#3498db', '#95a5a6']
    for ax, dept in zip(axes, DEPTS):
        done_cnt, active_cnt, idle_cnt = _calc(dept_recs[dept])
        sizes = [done_cnt, active_cnt, idle_cnt]
        labels = [f'已完成 {done_cnt}', f'进行中 {active_cnt}', f'未开工 {idle_cnt}']
        ax.pie(sizes, labels=labels, autopct='%1.0f%%', colors=colors,
               startangle=90, textprops={'fontsize': 10})
        ax.set_title(f'{dept} 工单进度', fontsize=12, fontweight='bold')
    fig.suptitle('工单完成进度分布（按部门）', fontsize=13, fontweight='bold')
    plt.tight_layout()
    return fig_to_base64(fig)


def chart_direct_wash(records):
    """直通 vs 非直通对比"""
    from collections import defaultdict
    agg = defaultdict(lambda: {'done': 0, 'plan': 0, 'wos': 0})
    for r in records:
        k = r.get('direct_wash') or '未标注'
        agg[k]['done'] += r['shift_done']
        agg[k]['plan'] += r['shift_plan']
        agg[k]['wos'] += 1
    labels = list(agg.keys())
    done = [agg[k]['done'] for k in labels]
    plan = [agg[k]['plan'] for k in labels]
    if not labels:
        return None
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(labels))
    w = 0.35
    ax.bar(x - w/2, plan, w, label='计划', color='#3498db', alpha=0.85)
    ax.bar(x + w/2, done, w, label='完成', color='#27ae60', alpha=0.85)
    for xi, v in zip(x - w/2, plan):
        ax.text(xi, v + 200, f'{v:,}', ha='center', fontsize=10, fontweight='bold')
    for xi, v in zip(x + w/2, done):
        ax.text(xi, v + 200, f'{v:,}', ha='center', fontsize=10, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=12)
    ax.set_title('直通 vs 非直通（清洗工序）', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    return fig_to_base64(fig)


def labor_line_stats(records):
    """人力效率统计：按产线聚合（同产线多工单共享标准人力，只算一次）
    返回 { (dept): {'lines': {line: manpower}, 'done': 总产出} }
    """
    from collections import defaultdict as _dd
    dept_stats = _dd(lambda: {'lines': {}, 'done': 0})
    for r in records:
        dept = get_dept(r['line'])[0]
        st = dept_stats[dept]
        st['done'] += r['shift_done']
        st['lines'].setdefault(r['line'], r.get('std_manpower') or 0)
    return dept_stats


def chart_labor_efficiency(records):
    """人力效率：按部门分左右（制造一部/制造二部），各显示人均产出"""
    DEPTS = ["制造一部", "制造二部"]
    dept_stats = labor_line_stats(records)
    # 按标准人力分组：组产出 = 组内各产线产出之和；人均 = 组产出 / (组内产线数 × 人力)
    def _groups(dept):
        agg = defaultdict(lambda: {'done': 0, 'lines': 0})
        for line, m in dept_stats[dept]['lines'].items():
            line_done = sum(r['shift_done'] for r in records
                            if r['line'] == line and get_dept(r['line'])[0] == dept)
            agg[m]['done'] += line_done
            agg[m]['lines'] += 1
        return agg

    aggs = {d: _groups(d) for d in DEPTS}
    if all(len(aggs[d]) == 0 for d in DEPTS):
        return None

    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))
    for ax, dept in zip(axes, DEPTS):
        agg = aggs[dept]
        items = sorted(agg.items())
        if not items:
            ax.text(0.5, 0.5, '无数据', ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f'{dept} 人力效率', fontsize=12, fontweight='bold')
            continue
        manpower = [k for k, _ in items]
        # 人均 = 组总产出 / (组内产线数 × 标准人力)
        per = [v['done'] / (v['lines'] * k) if k and v['lines'] else 0 for k, v in items]
        bars = ax.bar([str(m) for m in manpower], per, color='#27ae60', edgecolor='white')
        for xi, v in zip(range(len(manpower)), per):
            ax.text(xi, v + 20, f'{v:,.0f}', ha='center', fontsize=10, fontweight='bold')
        ax.set_title(f'{dept} 人均产出', fontsize=12, fontweight='bold')
        ax.set_xlabel('标准人力(人)')
        ax.grid(axis='y', alpha=0.3)
    fig.suptitle('人力效率（按部门）', fontsize=13, fontweight='bold')
    fig.tight_layout()
    return fig_to_base64(fig)


def generate_commentary(dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, records):
    """生成分析摘要与短评"""
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    
    # 总体判断
    if total_ach >= 80:
        overall = "✅ <b>整体表现良好</b>，达成率达标，产线运转正常。"
    elif total_ach >= 50:
        overall = "🟡 <b>整体表现一般</b>，近半数计划未完成，需关注落后产线。"
    elif total_ach >= 20:
        overall = f"🔴 <b>整体达成率偏低 ({total_ach:.1f}%)</b>，大量产线未达预期。"
    else:
        overall = f"🔴 <b>整体达成率极低 ({total_ach:.1f}%)</b>，仅少数产线有产出，需排查原因。"
    
    # 部门分析
    dept_comments = ""
    best_dept = (None, -1)
    worst_dept = (None, 999)
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if not d or d['lines'] == 0:
                continue
            ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
            if ach > best_dept[1]: best_dept = (f"{dept}{kes}", ach)
            if ach < worst_dept[1]: worst_dept = (f"{dept}{kes}", ach)
    
    if best_dept[0]:
        dept_comments += f"<li>🏆 <b>{best_dept[0]}</b> 达成率最高 ({best_dept[1]:.1f}%)</li>"
    if worst_dept[0] and worst_dept[0] != best_dept[0]:
        dept_comments += f"<li>⚠ <b>{worst_dept[0]}</b> 达成率最低 ({worst_dept[1]:.1f}%)</li>"
    
    # 零产出部门
    zero_depts = []
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['plan'] > 0 and d['done'] == 0:
                zero_depts.append(f"{dept}{kes}")
    if zero_depts:
        dept_comments += f"<li>⚫ <b>完全未产出：</b>{'、'.join(zero_depts)}</li>"
    
    # 未开动产线统计
    zero_comment = ""
    if len(zero_lines) > 40:
        zero_comment = f"<b>{len(zero_lines)} 条产线</b>有计划但无产出，占比 {len(zero_lines)/len(records)*100:.0f}%，大面积停产。"
    elif len(zero_lines) > 10:
        zero_comment = f"<b>{len(zero_lines)} 条产线</b>有计划但无产出，需跟进确认原因。"
    elif len(zero_lines) > 0:
        zero_comment = f"<b>{len(zero_lines)} 条产线</b>未开动，数量可控。"
    else:
        zero_comment = "所有计划产线均有产出，运转良好。"
    
    # 亮点产线
    highlight = ""
    if top5 and top5[0]['ach'] > 50:
        highlight = f"表现最佳：<b>{top5[0]['line']}</b>（{top5[0]['model'][:25]}）达成率 {top5[0]['ach']:.1f}%"
    
    # 班次
    shift_note = "白班时段，正常生产节奏。" if shift == "白班" else "夜班时段，关注交班衔接。"
    
    return f"""<div class="summary-box">
    <div class="summary-main">{overall} {shift_note}</div>
    <div class="summary-detail">
        <ul>{dept_comments}</ul>
        <p style="margin-top:8px">📌 {zero_comment}</p>
        {f'<p style="margin-top:4px;color:#27ae60">🌟 {highlight}</p>' if highlight else ''}
    </div>
</div>"""


def generate_html(records, dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, date_label, email_date):
    """生成 HTML 分析报告（PG 数据源增强版）"""
    now = datetime.now()

    # Chart
    chart_dept = chart_dept_ach(dept_data)
    chart_partner = chart_partner_top(records)
    chart_progress = chart_wo_progress(records)
    chart_wash = chart_direct_wash(records)
    chart_labor = chart_labor_efficiency(records)

    # 稼动率 = 实际产出 / 标准产能（capacit）
    sum_actual = sum(r['shift_done'] for r in records)
    sum_capacit = sum(r['capacit'] for r in records)
    utilization = sum_actual / sum_capacit * 100 if sum_capacit else 0
    # 人均产出 = 实际产出 / 标准人力（按产线去重，同产线多工单共享人力只算一次）
    _lstats = labor_line_stats(records)
    sum_mp = sum(m for v in _lstats.values() for m in v['lines'].values())
    per_head = sum_actual / sum_mp if sum_mp else 0
    # 在产工单数
    wo_active = sum(1 for r in records if r['wo_done'] < r['wo_total'])
    wo_done_cnt = sum(1 for r in records if r['wo_total'] > 0 and r['wo_done'] >= r['wo_total'])
    wo_idle = sum(1 for r in records if r['wo_done'] == 0)
    # 直通率
    wash_direct = sum(r['shift_done'] for r in records if r.get('direct_wash') == '直')
    wash_all = sum(r['shift_done'] for r in records if r.get('direct_wash'))
    wash_rate = wash_direct / wash_all * 100 if wash_all else 0

    # ---- 进度落后警示区块 ----
    lag_pool = {}
    for r in records:
        if r.get('diff') is None or r['diff'] <= 0:
            continue
        if r['wo_total'] > 0 and r['wo_done'] >= r['wo_total']:
            continue  # 已完成工单不算落后
        key = (r['line'], r['wo_id'])
        if key not in lag_pool or r['diff'] > lag_pool[key]['diff']:
            lag_pool[key] = r
    lag_list = sorted(lag_pool.values(), key=lambda x: x['diff'], reverse=True)
    if lag_list:
        rows_html = ""
        for r in lag_list[:15]:
            dept, kes = get_dept(r['line'])
            pct = r['diff_pct']
            rows_html += "<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num' style='color:#e74c3c;font-weight:700'>-%s</td><td class='num' style='color:#e74c3c'>-%.0f%%</td><td class='num'>第%s班</td></tr>" % (
                r['line'], kes, r['wo_id'][:22], r['model'][:30],
                f"{r['plan_sum']:,}", f"{r['wo_done']:,}",
                f"{r['diff']:,}", pct, r['nth_shift'])
        more_note = "<p style='margin-top:8px;color:#e74c3c;font-weight:600'>⚠ 共 %d 个工单进度落后（累计计划 &gt; 实际完成），以上为偏差最大 TOP %d。请优先排查：排产未动、机台故障、缺料等。</p>" % (len(lag_list), min(15, len(lag_list)))
        lag_section = '<div class="section" style="border-left:5px solid #e74c3c">' + \
    '<h2>🚨 进度落后警示（累计计划 vs 实际完成）</h2>' + \
    '<div class="table-wrap" style="max-height:400px"><table>' + \
    '<thead><tr><th>产线</th><th>课别</th><th>工单号</th><th>机种</th><th>累计计划</th><th>实际完成</th><th>落后量</th><th>落后%</th><th>班序</th></tr></thead>' + \
    '<tbody>' + rows_html + '</tbody></table></div>' + \
    more_note + '</div>'
    else:
        lag_section = '<div class="section" style="border-left:5px solid #27ae60">' + \
    '<h2>✅ 进度检查</h2>' + \
    '<p style="color:#27ae60">所有可追溯工单均按计划推进（累计计划 ≤ 实际完成），无落后。</p></div>'

    # ---- 客户排行表 ----
    from collections import defaultdict
    partner_agg = defaultdict(lambda: {'plan': 0, 'done': 0, 'wos': 0})
    for r in records:
        p = r.get('partner') or '未标注'
        partner_agg[p]['plan'] += r['shift_plan']
        partner_agg[p]['done'] += r['shift_done']
        partner_agg[p]['wos'] += 1
    partner_rows = ""
    for p, v in sorted(partner_agg.items(), key=lambda x: -x[1]['done'])[:10]:
        ach = v['done'] / v['plan'] * 100 if v['plan'] else 0
        ac = '#27ae60' if ach >= 80 else '#e74c3c' if ach < 50 else '#f39c12'
        partner_rows += '<tr><td>%s</td><td class="num">%d</td><td class="num">%s</td><td class="num" style="font-weight:700">%s</td><td class="num" style="color:%s;font-weight:700">%.1f%%</td></tr>' % (
            p, v['wos'], f"{v['plan']:,}", f"{v['done']:,}", ac, ach)

    # ---- 工单进度表（按部门）----
    def _progress_tbl(dept_recs, dept_name):
        d_done = [r for r in dept_recs if r['wo_total'] > 0 and r['wo_done'] >= r['wo_total']]
        d_active = [r for r in dept_recs if 0 < r['wo_done'] < r['wo_total']]
        d_idle = [r for r in dept_recs if r['wo_done'] == 0]
        done_out = sum(r['shift_done'] for r in d_done)
        active_out = sum(r['shift_done'] for r in d_active)
        return ('<div class="dept-sub"><h4>%s</h4>'
                '<table><thead><tr><th>状态</th><th>工单数</th><th>当班产出</th></tr></thead><tbody>'
                '<tr><td>✅ 已完成</td><td class="num">%d</td><td class="num" style="color:#27ae60">%s</td></tr>'
                '<tr><td>🔵 进行中</td><td class="num">%d</td><td class="num" style="color:#3498db">%s</td></tr>'
                '<tr><td>⚪ 未开工</td><td class="num">%d</td><td class="num">0</td></tr>'
                '</tbody></table></div>') % (
            dept_name, len(d_done), f"{done_out:,}", len(d_active), f"{active_out:,}", len(d_idle))

    dept_recs_all = {d: [r for r in records if get_dept(r['line'])[0] == d] for d in ["制造一部", "制造二部"]}
    progress_rows = _progress_tbl(dept_recs_all["制造一部"], "制造一部") + _progress_tbl(dept_recs_all["制造二部"], "制造二部")

    # ---- 人力效率表（按部门）----
    def _labor_tbl(dept, dept_name):
        stats = labor_line_stats(records).get(dept, {'lines': {}, 'done': 0})
        # 按标准人力分组
        mp_agg = defaultdict(lambda: {'done': 0, 'lines': 0})
        for line, m in stats['lines'].items():
            line_done = sum(r['shift_done'] for r in records
                            if r['line'] == line and get_dept(r['line'])[0] == dept)
            mp_agg[m]['done'] += line_done
            mp_agg[m]['lines'] += 1
        rows = ""
        for m, v in sorted(mp_agg.items()):
            people = v['lines'] * m  # 组内总人力 = 产线数 × 标准人力
            per = v['done'] / people if people else 0
            rows += '<tr><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td><td class="num">%s</td><td class="num" style="font-weight:700">%s</td></tr>' % (
                m, v['lines'], v['lines'] * m, f"{v['done']:,}", f"{per:,.0f}")
        return ('<div class="dept-sub"><h4>%s</h4>'
                '<table><thead><tr><th>标准人力</th><th>产线数</th><th>总人力</th><th>总产出</th><th>人均产出</th></tr></thead>'
                '<tbody>%s</tbody></table></div>') % (dept_name, rows)

    labor_rows = _labor_tbl("制造一部", "制造一部") + _labor_tbl("制造二部", "制造二部")

    # ---- 产线明细表（增强：加客户/稼动率）----
    line_rows = ""
    DEPTS = ["制造一部", "制造二部"]
    KES_ORDER = {"制造一部": ["冲压一课","冲压二课","冲压三课"], "制造二部": ["清洗一课","清洗二课","清洗三课"]}
    groups = defaultdict(list)
    for r in records:
        dept, kes = get_dept(r['line'])
        groups[(dept, kes)].append(r)
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = (dept, kes)
            if key not in groups:
                continue
            lines = sorted(groups[key], key=lambda x: x['ach'], reverse=True)
            active = [r for r in lines if r['shift_done'] > 0]
            g_plan = sum(r['shift_plan'] for r in active)
            g_done = sum(r['shift_done'] for r in active)
            g_ach = g_done / g_plan * 100 if g_plan else 0
            g_color = '#e74c3c' if g_ach < 30 else '#f39c12' if g_ach < 60 else '#27ae60'
            active_note = "（%d/%d线有产出）" % (len(active), len(lines)) if len(active) < len(lines) else ""
            line_rows += """<tr style="background:#f0f4f8;font-weight:700">
                <td colspan="2">%s · %s</td><td>%d 条产线%s</td>
                <td class="num">%s</td><td class="num">%s</td>
                <td class="ach" style="color:%s">%.1f%%</td>
                <td></td><td></td><td></td><td></td><td></td>
            </tr>""" % (dept, kes, len(lines), active_note, f"{g_plan:,}", f"{g_done:,}", g_color, g_ach)
            for r in lines:
                ach = r['ach']
                color = '#e74c3c' if ach == 0 and r['shift_plan'] > 0 else '#27ae60' if ach >= 60 else '#f39c12'
                bg = '#fff5f5' if ach == 0 and r['shift_plan'] > 0 else ''
                util = r['shift_done'] / r['capacit'] * 100 if r['capacit'] else 0
                util_txt = "%.0f%%" % util if r['capacit'] else '-'
                nth = r.get('nth_shift')
                diff = r.get('diff')
                if nth:
                    done_all = (r['wo_total'] > 0 and r['wo_done'] >= r['wo_total'])
                    if done_all:
                        nth_txt = "共%d班✓" % nth; nth_style = 'color:#27ae60'
                    elif diff is not None and diff > 0:
                        nth_txt = "第%d班 落后%s" % (nth, f"{diff:,}"); nth_style = 'color:#e74c3c;font-weight:700'
                    else:
                        nth_txt = "第%d班" % nth; nth_style = ''
                else:
                    nth_txt = '—'; nth_style = 'color:#bbb'
                line_rows += """<tr style="background:%s">
                <td>%s</td><td>%s</td><td>%s</td>
                <td class="num">%s</td><td class="num">%s</td>
                <td class="ach" style="color:%s">%.1f%%</td>
                <td class="num">%s</td><td class="num">%s</td>
                <td class="num">%s</td><td>%s</td>
                <td class="num" style="%s">%s</td>
            </tr>""" % (bg, r['line'], r['model'][:30], r['wo_id'][:22],
                        f"{r['shift_plan']:,}", f"{r['shift_done']:,}", color, ach,
                        f"{r['wo_total']:,}", f"{r['wo_done']:,}",
                        util_txt, r.get('partner') or '-', nth_style, nth_txt)

    ach_color = '#e74c3c' if total_ach < 30 else '#f39c12' if total_ach < 60 else '#27ae60'

    # 部门汇总
    dept_rows = ""
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = f"{dept}-{kes}"
            d = dept_data.get(key)
            if d and d['lines'] > 0:
                ach = d['done'] / d['plan'] * 100 if d['plan'] else 0
                color = '#e74c3c' if ach < 30 else '#f39c12' if ach < 60 else '#27ae60'
                active_info = "（%d/%d线有产出）" % (d['active_lines'], d['lines']) if d['active_lines'] < d['lines'] else ""
                dept_rows += """<tr>
                    <td>%s</td><td>%s</td><td>%d%s</td>
                    <td class="num">%s</td><td class="num">%s</td>
                    <td class="ach" style="color:%s">%.1f%%</td>
                </tr>""" % (dept, kes, d['lines'], active_info, f"{d['plan']:,}", f"{d['done']:,}", color, ach)

    # TOP5
    top5_html = "".join(
        "<tr><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='ach' style='color:#27ae60'>%.1f%%</td></tr>" % (
            r['line'], r['model'][:35], f"{r['shift_plan']:,}", f"{r['shift_done']:,}", r['ach'])
        for r in top5)

    # 摘要
    commentary = generate_commentary(dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, records)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>当班生产分析(PG) - {date_label} {shift}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'WenQuanYi Zen Hei', 'Microsoft YaHei', sans-serif;
        background: #f0f2f5; color: #333; padding: 20px;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    .header {{
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        color: white; padding: 24px 36px; border-radius: 14px; margin-bottom: 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
    }}
    .header h1 {{ font-size: 24px; margin-bottom: 4px; }}
    .header .meta {{ font-size: 13px; opacity: 0.8; }}
    .kpi-row {{ display: flex; gap: 14px; margin-bottom: 20px; }}
    .kpi-card {{
        flex: 1; background: white; border-radius: 12px; padding: 18px 22px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06); text-align: center;
    }}
    .kpi-card .label {{ font-size: 13px; color: #888; }}
    .kpi-card .value {{ font-size: 28px; font-weight: 700; margin: 4px 0; }}
    .kpi-card .sub {{ font-size: 12px; color: #aaa; }}
    .section {{
        background: white; border-radius: 12px; padding: 22px 26px;
        margin-bottom: 18px; box-shadow: 0 2px 10px rgba(0,0,0,0.06);
    }}
    .section h2 {{ font-size: 17px; color: #1a1a2e; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 2px solid #3498db; }}
    .chart-img {{ max-width: 100%; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    thead th {{ background: #f8f9fa; padding: 9px 10px; text-align: left; font-weight: 600; border-bottom: 2px solid #dee2e6; }}
    tbody td {{ padding: 7px 10px; border-bottom: 1px solid #f1f3f5; }}
    tbody tr:hover {{ background: #f8f9ff; }}
    .num {{ text-align: right; }}
    .ach {{ text-align: right; font-weight: 600; }}
    .table-wrap {{ max-height: 550px; overflow-y: auto; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
    .dept-sub {{ background:#f8fafc; border-radius:8px; padding:12px; margin-bottom:12px; }}
    .dept-sub h4 {{ font-size:14px; color:#1a5276; margin-bottom:8px; padding-left:8px; border-left:3px solid #3498db; }}
    .dept-tbl-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    @media (max-width: 1100px) {{ .grid-2 {{ grid-template-columns: 1fr; }} .kpi-row {{ flex-wrap: wrap; }} .dept-tbl-2 {{ grid-template-columns:1fr; }} }}
    .badge-shift {{ display: inline-block; padding: 3px 14px; border-radius: 14px; font-size: 14px; margin-left: 10px; font-weight: 600; }}
    .badge-day {{ background: #f39c12; color: white; }}
    .badge-night {{ background: #34495e; color: #ecf0f1; }}
    .summary-box {{
        background: linear-gradient(135deg, #f8f9ff, #eef1f8);
        border-left: 5px solid #3498db; border-radius: 10px;
        padding: 18px 24px; margin-bottom: 20px; line-height: 1.7;
    }}
    .summary-main {{ font-size: 15px; color: #1a1a2e; margin-bottom: 8px; }}
    .summary-detail {{ font-size: 13px; color: #555; }}
    .summary-detail ul {{ list-style: none; padding: 0; }}
    .summary-detail li {{ padding: 3px 0; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>🏭 当班生产情况分析
        <span class="badge-shift {'badge-day' if shift == '白班' else 'badge-night'}">{shift}</span>
    </h1>
    <div class="meta">
        数据时间: {date_label} &nbsp;|&nbsp; 工单数: {len(records)} &nbsp;|&nbsp; 数据源: Oracle GET_VALID_WOW &nbsp;|&nbsp; 生成: {now.strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>

<div class="kpi-row">
    <div class="kpi-card"><div class="label">📋 总计划</div><div class="value" style="color:#3498db">{total_plan:,}</div><div class="sub">件</div></div>
    <div class="kpi-card"><div class="label">✅ 总产出</div><div class="value" style="color:#27ae60">{total_done:,}</div><div class="sub">件</div></div>
    <div class="kpi-card"><div class="label">📈 达成率</div><div class="value" style="color:{ach_color}">{total_ach:.1f}%</div><div class="sub">{'🔴预警' if total_ach<30 else '🟡偏低' if total_ach<60 else '🟢正常'}</div></div>
    <div class="kpi-card"><div class="label">⚙️ 产出达成率</div><div class="value" style="color:#8e44ad">{utilization:.1f}%</div><div class="sub">产出/标准产能</div></div>
    <div class="kpi-card"><div class="label">👥 人均产出</div><div class="value" style="color:#16a085">{per_head:,.0f}</div><div class="sub">件/人</div></div>
    <div class="kpi-card"><div class="label">📦 在产工单</div><div class="value" style="color:#e67e22">{wo_active}</div><div class="sub">已完成{wo_done_cnt} · 未开工{wo_idle}</div></div>
</div>

{commentary}

{lag_section}

<div class="grid-2">
    <div class="section">
        <h2>🏆 客户产出排行 TOP10</h2>
        <div class="table-wrap">
        <table>
            <thead><tr><th>客户</th><th>工单数</th><th>计划</th><th>产出</th><th>达成率</th></tr></thead>
            <tbody>{partner_rows}</tbody>
        </table>
        </div>
    </div>
    <div class="section">
        <h2>📦 工单进度分布</h2>
        {f'<img class="chart-img" src="data:image/png;base64,{chart_progress}" alt="工单进度">' if chart_progress else ''}
        <div class="dept-tbl-2">{progress_rows}</div>
    </div>
</div>

<div class="grid-2">
    <div class="section">
        <h2>💧 直通 vs 非直通</h2>
        {f'<img class="chart-img" src="data:image/png;base64,{chart_wash}" alt="直通对比">' if chart_wash else ''}
        <p style="margin-top:8px;font-size:13px;color:#555">直通占比: <b style="color:#27ae60">{wash_rate:.1f}%</b>（直通产出 {wash_direct:,} / 合计 {wash_all:,}）</p>
    </div>
    <div class="section">
        <h2>👥 人力效率</h2>
        {f'<img class="chart-img" src="data:image/png;base64,{chart_labor}" alt="人力效率">' if chart_labor else ''}
        <div class="dept-tbl-2">{labor_rows}</div>
    </div>
</div>

<div class="section">
    <h2>📊 部门达成率 & 计划/完成对比</h2>
    {f'<img class="chart-img" src="data:image/png;base64,{chart_dept}" alt="部门对比">' if chart_dept else ''}
</div>

<div class="grid-2">
    <div class="section">
        <h2>📋 部门汇总</h2>
        <table>
            <thead><tr><th>部门</th><th>课别</th><th>产线</th><th>计划</th><th>完成</th><th>达成率</th></tr></thead>
            <tbody>{dept_rows}</tbody>
        </table>
    </div>
    <div class="section">
        <h2>🏆 TOP 5 产线</h2>
        <table>
            <thead><tr><th>产线</th><th>机型</th><th>计划</th><th>完成</th><th>达成率</th></tr></thead>
            <tbody>{top5_html}</tbody>
        </table>
    </div>
</div>

<div class="section">
    <h2>🔍 产线明细（按部门分组 · 达成率排序）</h2>
    <div class="table-wrap">
    <table>
        <thead><tr><th>产线</th><th>机型</th><th>工单号</th><th>计划</th><th>完成</th><th>达成率</th><th>工单总量</th><th>工单完成</th><th>产出达成率</th><th>客户</th><th>班序</th></tr></thead>
        <tbody>{line_rows}</tbody>
    </table>
    </div>
</div>

</div>
</body>
</html>"""
    return html


def send_report(report_text, shift, date_label, html_name=""):
    """发送分析邮件"""
    subject = f"[测试]当班生产分析 - {date_label} {shift}"
    
    # 追加 HTML 报告链接
    if html_name:
        report_text += f"\n\n📊 完整 HTML 报告: {REPORT_URL_BASE}/{html_name}"
    
    msg = MIMEMultipart()
    msg['From'] = f"{SENDER_NAME} <{SENDER}>"
    to_addrs = [addr for addr, _ in RECIPIENTS]
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(report_text, 'plain', 'utf-8'))

    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    server.login(USERNAME, PASSWORD)
    server.sendmail(SENDER, to_addrs, msg.as_string())
    server.quit()
    return to_addrs


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 读取 PG 当班数据...")

    # 从 PG 读取最新同步数据（替代邮件）
    records, sync_time = get_latest_shift_data()
    if not records:
        print("  ⚠ 无数据，退出")
        return 1

    # 当前班次判断（基于最新同步时间）
    date_str = sync_time.strftime('%a, %d %b %Y %H:%M:%S +0800')
    shift = "白班" if 8 <= sync_time.hour < 20 else "夜班"
    # 生产日期 = 数据里的 tplan_start（快照隔天生成，数据是前一天的生产）
    if records and records[0].get('tplan_start'):
        tplan = records[0]['tplan_start']
        if hasattr(tplan, 'strftime'):
            date_label = f"{tplan.strftime('%m/%d')} {shift}"
        else:
            date_label = f"{tplan} {shift}"
    else:
        date_label = sync_time.strftime("%m/%d %H:%M")
    print(f"  数据时间: {sync_time} | 生产日期: {date_label} | {len(records)} 条工单记录")

    # 计算班序（该工单第几个班生产）+ 进度偏差
    # 历史数据源：plan_actual_hourly（每小时同步积累）
    try:
        shift_seq = calc_shift_seq_pg(records, sync_time)
    except Exception as e:
        print(f"  ⚠ 班序计算失败: {e}")
        shift_seq = {}
    for r in records:
        info = shift_seq.get((r['line'], r['wo_id']))
        if info:
            r['nth_shift'] = info['nth']
            r['plan_sum'] = info['plan_sum']
            r['wo_done_hist'] = info['done']
            r['diff'] = info['diff']
            r['diff_pct'] = info['diff_pct']
        else:
            r['nth_shift'] = None
            r['diff'] = None
    n_with_seq = sum(1 for r in records if r['nth_shift'] is not None)
    n_lag = sum(1 for r in records if r.get('diff') and r['diff'] > 0)
    print(f"  班序: {n_with_seq}/{len(records)} 工单可追溯 | 落后 {n_lag} 个")

    # 分析
    print(f"  {len(records)} 条工单 → 分析中...")
    report_text, shift, date_label, dept_data, top5, zero_lines, total_plan, total_done, total_ach = analyze(
        records, date_str, date_label_override=date_label, shift_override=shift)

    # 生成 HTML 报告
    print(f"  生成 HTML 报告...")
    html = generate_html(records, dept_data, top5, zero_lines, total_plan, total_done, total_ach, shift, date_label, date_str)
    
    # 保存 HTML
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    html_name = f"当班分析PG_{now.strftime('%Y%m%d_%H%M')}.html"
    html_path = OUTPUT_DIR / html_name
    html_path.write_text(html, encoding='utf-8')
    print(f"  ✅ HTML: {html_path} ({html_path.stat().st_size/1024:.0f} KB)")

    # 发送邮件（含 HTML 链接）
    to_addrs = send_report(report_text, shift, date_label, html_name)
    print(f"  ✅ 已发送 → {', '.join(to_addrs)}")
    return 0


if __name__ == '__main__':
    import sys
    ret = main()
    import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])
    sys.exit(ret)

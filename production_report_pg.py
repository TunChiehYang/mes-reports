#!/usr/bin/env python3
"""生产日报（PG 版）— 基于新服务器 plan_actual_detail 16列新格式
数据源: 10.2.20.127 mes_plan.plan_actual_detail（最新快照）
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import psycopg2
import psycopg2.extras
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import base64
import io

OUT = Path("/mnt/d/outputHTML")

for f in ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei']:
    if f in {x.name for x in fm.fontManager.ttflist}:
        plt.rcParams['font.family'] = f
        break
plt.rcParams['axes.unicode_minus'] = False

PG = dict(host='10.2.20.127', port=5432, user='postgres',
          password='Chia@1234', dbname='mes_plan')


def get_dept(line_id):
    """部门分类：NA/NB=制造一部，NQ=制造二部"""
    lid = str(line_id).strip().upper()
    if lid.startswith(('NA', 'NB')):
        return "制造一部"
    if lid.startswith('NQ'):
        return "制造二部"
    return "其他"


def to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    b = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b


def calc_shift_seq(rows, latest):
    """计算每个工单当前是第几个班生产（开始有产出=第1班）+ 进度偏差
    数据源: plan_actual_hourly（Oracle GET_VALID_WOW 每小时同步积累）
    班次键 = (tplan_start, clas_type)
    rows: 目标日期的所有行（白班+夜班完整）
    latest: 目标日期（datetime）
    返回 { (line_id, wo_id): {'nth':n, 'plan_sum':p, 'done':d, 'diff':x, 'diff_pct':y} }
    评估基准：目标日期最后班次（前一天完整数据，不减一）
    """
    conn = None
    try:
        conn = psycopg2.connect(**PG)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # 当前工单集合
        wanted = {(r['line_id'], r['wo_id']) for r in rows}
        # 查这些工单的全部历史（目标日期往前30天）
        from datetime import timedelta as _td
        d0 = latest - _td(days=30)
        cur.execute("""
            SELECT line_id, wo_id, tplan_start, clas_type, total_qty, wo_plan_qty,
                   actual_qty, output_qty, sync_time
            FROM plan_actual_hourly
            WHERE tplan_start IS NOT NULL AND sync_time <= %s
              AND wo_id IS NOT NULL AND wo_id != ''
            ORDER BY sync_time
        """, (latest,))
        hist = cur.fetchall()
        cur.close()
    except Exception as e:
        print(f"  ⚠ 班序计算失败: {e}")
        if conn:
            conn.close()
        return {}
    finally:
        if conn:
            conn.close()

    if not hist:
        return {}

    # 只保留当前工单
    hist = [r for r in hist if (r['line_id'], r['wo_id']) in wanted]
    if not hist:
        return {}

    # 班次键：tplan_start(日期) + clas_type（白班在前，夜班在后）
    def shift_key(r):
        d = r['tplan_start']
        if hasattr(d, 'date'):
            d = d.date()
        return (str(d), 0 if r['clas_type'] == '白班' else 1)

    # 当前班次 = 目标日期最后班次（夜班优先，否则白班）
    target_day = None
    for r in rows:
        if r.get('tplan_start'):
            d = r['tplan_start']
            if hasattr(d, 'date'):
                d = d.date()
            target_day = str(d)
            break
    cur_shift = None
    if target_day:
        has_night = any(r.get('clas_type') == '夜班' for r in rows)
        cur_shift = (target_day, 1 if has_night else 0)

    # 按 (line, wo) 分组，班次聚合（同一班次多次快照取最新）
    from collections import OrderedDict
    groups = OrderedDict()
    for r in hist:
        key = (r['line_id'], r['wo_id'])
        sk = shift_key(r)
        g = groups.setdefault(key, OrderedDict())
        if sk not in g or r['sync_time'] > g[sk][4]:
            g[sk] = (r['wo_plan_qty'], r['actual_qty'], r['output_qty'], r['total_qty'], r['sync_time'])

    result = {}
    for key, shifts in groups.items():
        sorted_shifts = sorted(shifts.items(), key=lambda kv: kv[0])
        # 首次有产出班次（actual_qty>0 或 output_qty>0）
        first_idx = None
        for i, (sk, (plan, act, out, tot, ts)) in enumerate(sorted_shifts):
            if (act or 0) > 0 or (out or 0) > 0:
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
        # 评估基准：目标日期最后班次（前一天数据完整，不减一）
        eval_idx = cur_idx
        if eval_idx < first_idx or eval_idx < 0:
            continue
        nth = eval_idx - first_idx + 1
        # 累计计划（从首次产出班到评估班）与实际完成
        wo_total = shifts[sorted_shifts[eval_idx][0]][3]
        plan_sum = sum(shifts[sk][0] or 0 for sk, _ in sorted_shifts[first_idx:eval_idx + 1])
        if wo_total and wo_total > 0:
            plan_sum = min(plan_sum, wo_total)
        # 实际完成 = 评估班的累计产出 output_qty（优先），否则当班产出
        done = shifts[sorted_shifts[eval_idx][0]][2] or shifts[sorted_shifts[eval_idx][0]][1] or 0
        diff = plan_sum - done  # >0 = 落后
        diff_pct = diff / plan_sum * 100 if plan_sum else 0
        result[key] = {'nth': nth, 'plan_sum': plan_sum, 'done': done,
                       'diff': diff, 'diff_pct': diff_pct}
    return result


def main():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 数据源: plan_daily_detail（Oracle GET_VALID_WOW 完整17列）
    # 日报 = 前一天完整数据（白班+夜班），按 (line_id, wo_id, clas_type) 去重取最新 sync_time
    # 支持参数指定 tplan_start 日期便于测试: python3 production_report_pg.py [YYYY-MM-DD]
    import sys as _sys
    from datetime import timedelta as _td
    if len(_sys.argv) > 1:
        target_date = _sys.argv[1]
    else:
        # 缺省 = 昨天（日报上午8:30生成，取前一天完整数据）
        target_date = (datetime.now() - _td(days=1)).strftime('%Y-%m-%d')
    cur.execute("""
        SELECT DISTINCT ON (line_id, wo_id, clas_type) *
        FROM plan_daily_detail
        WHERE tplan_start = %s
        ORDER BY line_id, wo_id, clas_type, sync_time DESC
    """, (target_date,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        print(f"⚠ {target_date} 无数据（可能是周末/未排产），跳过日报生成")
        return

    df = [dict(r) for r in rows]
    print(f"数据源: plan_daily_detail @ {target_date} | {len(df)} 行（白班+夜班完整）")

    # 目标日期（用于班序历史查询边界 = 前一天最后一刻）
    latest = datetime.strptime(target_date, '%Y-%m-%d') + _td(days=1) - _td(seconds=1)

    # ── 班序 + 进度偏差（基于历史快照）──
    shift_seq = calc_shift_seq(rows, latest)
    for r in df:
        info = shift_seq.get((r['line_id'], r['wo_id']))
        if info:
            r['nth_shift'] = info['nth']
            r['plan_sum'] = info['plan_sum']
            r['wo_done_hist'] = info['done']
            r['diff'] = info['diff']
            r['diff_pct'] = info['diff_pct']
        else:
            r['nth_shift'] = None
            r['diff'] = None
    n_lag = sum(1 for r in df if r.get('diff') and r['diff'] > 0)
    print(f"  班序可追溯 {sum(1 for r in df if r['nth_shift'] is not None)}/{len(df)} | 落后 {n_lag} 个")

    # ── 基础统计 ──
    total_lines = len({r['line_id'] for r in df})
    with_output = [r for r in df if (r['actual_qty'] or 0) > 0]
    active_lines = len({r['line_id'] for r in with_output})
    total_plan = sum(r['wo_plan_qty'] or 0 for r in df)
    total_actual = sum(r['actual_qty'] or 0 for r in df)
    ach_all = total_actual / total_plan * 100 if total_plan else 0

    # 状态分布
    status_cnt = {}
    for r in df:
        st = r['reason'] or '未标注'
        status_cnt[st] = status_cnt.get(st, 0) + 1

    # 部门统计（仅统计有产出）
    dept_agg = {}
    for r in with_output:
        d = get_dept(r['line_id'])
        if d not in dept_agg:
            dept_agg[d] = {'plan': 0, 'actual': 0, 'lines': set()}
        dept_agg[d]['plan'] += r['wo_plan_qty'] or 0
        dept_agg[d]['actual'] += r['actual_qty'] or 0
        dept_agg[d]['lines'].add(r['line_id'])

    # 班次对比（按部门 × 班次）
    shift_agg = {}
    for r in with_output:
        d = get_dept(r['line_id'])
        s = r['clas_type'] or '未标注'
        key = (d, s)
        if key not in shift_agg:
            shift_agg[key] = {'plan': 0, 'actual': 0}
        shift_agg[key]['plan'] += r['wo_plan_qty'] or 0
        shift_agg[key]['actual'] += r['actual_qty'] or 0

    # 产线汇总（有产出）
    line_map = {}
    for r in with_output:
        lid = r['line_id']
        if lid not in line_map:
            line_map[lid] = {'plan': 0, 'actual': 0, 'wo': r['wo_id'],
                             'model': r['model_no'], 'partner': r['partner_name'],
                             'shifts': set()}
        line_map[lid]['plan'] += r['wo_plan_qty'] or 0
        line_map[lid]['actual'] += r['actual_qty'] or 0
        if r['clas_type']:
            line_map[lid]['shifts'].add(r['clas_type'])

    line_rows = []
    for lid, v in line_map.items():
        ach = v['actual'] / v['plan'] * 100 if v['plan'] else 0
        line_rows.append({
            'line': lid, 'wo': v['wo'], 'model': v['model'],
            'partner': v['partner'], 'plan': v['plan'], 'actual': v['actual'],
            'ach': ach, 'shifts': '/'.join(sorted(v['shifts']))
        })
    line_rows.sort(key=lambda x: x['ach'], reverse=True)

    # ── 图表 ──
    # 图1: 状态分布饼图
    fig1, ax1 = plt.subplots(figsize=(7, 5))
    labels = list(status_cnt.keys())
    sizes = list(status_cnt.values())
    colors = ['#27ae60', '#f39c12', '#95a5a6', '#3498db', '#e74c3c', '#9b59b6'][:len(labels)]
    ax1.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors,
            startangle=90, textprops={'fontsize': 11})
    ax1.set_title('产线状态分布', fontsize=14, fontweight='bold')
    plt.tight_layout()
    c1 = to_b64(fig1)

    # 图2: 部门对比
    fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    dept_names = list(dept_agg.keys())
    dept_actuals = [dept_agg[d]['actual'] for d in dept_names]
    bars = ax1.bar(dept_names, dept_actuals, color=['#3498db', '#e67e22', '#95a5a6'])
    for b, v in zip(bars, dept_actuals):
        ax1.text(b.get_x() + b.get_width() / 2, b.get_height() + 500,
                 f'{v:,}', ha='center', fontsize=12, fontweight='bold')
    ax1.set_title('部门实际产出', fontsize=13, fontweight='bold')
    ax1.grid(axis='y', alpha=0.3)
    dept_ach = [dept_agg[d]['actual'] / dept_agg[d]['plan'] * 100 if dept_agg[d]['plan'] else 0
                for d in dept_names]
    bars2 = ax2.bar(dept_names, dept_ach, color=['#3498db', '#e67e22', '#95a5a6'])
    for b, v in zip(bars2, dept_ach):
        ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 1,
                 f'{v:.1f}%', ha='center', fontsize=12, fontweight='bold')
    ax2.axhline(y=80, color='#27ae60', linestyle='--', alpha=0.6, label='80% 目标')
    ax2.set_title('部门达成率', fontsize=13, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    c2 = to_b64(fig2)

    # 图3: 班次对比（制造一部/二部 × 白班/夜班 分组柱状图）
    fig3, ax = plt.subplots(figsize=(10, 5))
    dept_names = ['制造一部', '制造二部']
    shift_names = ['白班', '夜班']
    colors3 = {'白班': '#f39c12', '夜班': '#5a6a7a'}
    x = np.arange(len(dept_names))
    w = 0.35
    for si, sh in enumerate(shift_names):
        vals = [shift_agg.get((d, sh), {}).get('actual', 0) for d in dept_names]
        bars = ax.bar(x + (si - 0.5) * w, vals, w, label=f'{sh}',
                      color=colors3[sh], edgecolor='white')
        for b, v in zip(bars, vals):
            if v > 0:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 300,
                        f'{v:,}', ha='center', fontsize=10, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(dept_names, fontsize=12)
    ax.set_ylabel('实际产出', fontsize=11)
    ax.set_title('白班/夜班产出对比（按部门）', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    c3 = to_b64(fig3)

    # 图4: TOP15 产线达成率
    fig4, ax = plt.subplots(figsize=(12, 5))
    top15 = line_rows[:15]
    names = [r['line'] for r in top15]
    vals = [r['ach'] for r in top15]
    colors4 = ['#3498db' if n.startswith(('NA', 'NB')) else '#e67e22' for n in names]
    bars = ax.bar(range(len(names)), vals, color=colors4)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha='right', fontsize=9)
    for i, v in enumerate(vals):
        ax.text(i, v + 1, f'{v:.0f}%', ha='center', fontsize=9)
    avg = np.mean(vals) if vals else 0
    ax.axhline(y=avg, color='#e74c3c', linestyle='--', label=f'均值 {avg:.1f}%')
    ax.set_ylabel('达成率 %')
    ax.set_title('TOP 15 产线达成率', fontsize=14, fontweight='bold')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    c4 = to_b64(fig4)

    # ── 明细表 ──
    tbl = ''
    for r in line_rows:
        ac = '#27ae60' if r['ach'] >= 80 else '#e74c3c' if r['ach'] < 50 else '#f39c12'
        tbl += f'''<tr>
            <td>{r['line']}</td>
            <td style="font-size:11px">{r['wo'] or '-'}</td>
            <td style="font-size:11px">{r['model'] or '-'}</td>
            <td style="font-size:11px">{r['partner'] or '-'}</td>
            <td>{r['shifts']}</td>
            <td class="num">{r['plan']:,}</td>
            <td class="num" style="font-weight:bold">{r['actual']:,}</td>
            <td class="num" style="color:{ac};font-weight:bold">{r['ach']:.1f}%</td>
        </tr>'''

    # 状态表
    status_tbl = ''
    for st, cnt in sorted(status_cnt.items(), key=lambda x: -x[1]):
        qty = sum(r['actual_qty'] or 0 for r in df if (r['reason'] or '未标注') == st)
        status_tbl += f'<tr><td>{st}</td><td class="num">{cnt}</td><td class="num">{qty:,}</td></tr>'

    # 部门×班次明细表
    shift_tbl = ''
    for d in ['制造一部', '制造二部']:
        for s in ['白班', '夜班']:
            v = shift_agg.get((d, s), {'plan': 0, 'actual': 0})
            ach = v['actual'] / v['plan'] * 100 if v['plan'] else 0
            ac = '#27ae60' if ach >= 80 else '#e74c3c' if ach < 50 else '#f39c12'
            shift_tbl += (f'<tr><td>{d}</td><td>{s}</td>'
                          f'<td class="num">{v["plan"]:,}</td>'
                          f'<td class="num">{v["actual"]:,}</td>'
                          f'<td class="num" style="color:{ac};font-weight:bold">{ach:.1f}%</td></tr>')

    # ── 摘要 ──
    d1 = dept_agg.get('制造一部', {'actual': 0})
    d2 = dept_agg.get('制造二部', {'actual': 0})
    idle = total_lines - active_lines
    # 生产日期 = 目标日期（前一天白班+夜班完整数据）
    date_label = target_date.replace('-', '')
    date_show = target_date
    summary = f'''<p>📅 <b>{date_show}</b> 生产日报（前一日白班+夜班完整数据，Oracle 直连）· {total_lines} 条产线，其中 <b>{active_lines}</b> 条有产出，{idle} 条空闲/待排。</p>
<p>📊 总计划 <b>{total_plan:,}</b>，总实际产出 <b>{total_actual:,}</b>，综合达成率 <b>{ach_all:.1f}%</b>。</p>
<p>🏭 制造一部（冲压）产出 {d1.get("actual", 0):,}，制造二部（清洗）产出 {d2.get("actual", 0):,}。</p>
<p>📦 已完成切线 <b>{status_cnt.get("已完成切线", 0)}</b> 条产线，有计划但无切线 <b>{status_cnt.get("有计划但无切线", 0)}</b> 条，无计划 <b>{status_cnt.get("无计划", 0)}</b> 条。</p>'''

    # ── 进度落后警示区块 ──
    # 按 (line_id, wo_id) 去重（同工单白班/夜班两行只保留一条）
    lag_pool = {}
    for r in df:
        if r.get('diff') is None or r['diff'] <= 0:
            continue
        if r['total_qty'] and r['total_qty'] > 0 and (r['output_qty'] or 0) >= r['total_qty']:
            continue  # 已完成工单不算落后
        key = (r['line_id'], r['wo_id'])
        # 同工单多行取 diff 最大的一条
        if key not in lag_pool or r['diff'] > lag_pool[key]['diff']:
            lag_pool[key] = r
    lag_list = sorted(lag_pool.values(), key=lambda x: x['diff'], reverse=True)
    if lag_list:
        lag_rows = ""
        for r in lag_list[:15]:
            dept = get_dept(r['line_id'])
            pct = r['diff_pct']
            lag_rows += f'''<tr>
                <td><b>{r['line_id']}</b></td><td>{dept}</td><td>{r['wo_id'] or '-'}</td><td>{r['model_no'] or '-'}</td>
                <td class="num">{r['plan_sum']:,}</td>
                <td class="num">{r['wo_done_hist']:,}</td>
                <td class="num" style="color:#e74c3c;font-weight:bold">-{r['diff']:,}</td>
                <td class="num" style="color:#e74c3c">-{pct:.0f}%</td>
                <td class="num">第{r['nth_shift']}班</td>
            </tr>'''
        lag_section = f'''<div class="section" style="border-left:5px solid #e74c3c">
<h2>🚨 进度落后警示（累计计划 vs 实际完成）</h2>
<div class="tbw" style="max-height:400px"><table>
<thead><tr><th>产线</th><th>部门</th><th>工单号</th><th>机种</th><th>累计计划</th><th>实际完成</th><th>落后量</th><th>落后%</th><th>班序</th></tr></thead>
<tbody>{lag_rows}</tbody></table></div>
<p style="margin-top:8px;color:#e74c3c;font-weight:600">⚠ 共 {len(lag_list)} 个工单进度落后（累计计划 &gt; 实际完成），以上为偏差最大 TOP {min(15, len(lag_list))}。请优先排查：排产未动、机台故障、缺料等。</p>
</div>'''
    else:
        lag_section = '''<div class="section" style="border-left:5px solid #27ae60">
<h2>✅ 进度检查</h2>
<p style="color:#27ae60">所有可追溯工单均按计划推进（累计计划 ≤ 实际完成），无落后。</p>
</div>'''

    # ── HTML ──
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    html = f'''<!DOCTYPE html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>生产日报（PG版）</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Microsoft YaHei','WenQuanYi Zen Hei',sans-serif;background:#f0f2f5;color:#333}}
.header{{background:linear-gradient(135deg,#1a5276,#2c3e50);color:#fff;padding:20px 32px}}
.header h1{{font-size:22px;margin-bottom:4px}}
.header .meta{{font-size:12px;opacity:.85}}
.container{{max-width:1300px;margin:0 auto;padding:14px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}}
.kpi-card{{background:#fff;border-radius:10px;padding:14px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.kpi-card .num{{font-size:24px;font-weight:800;margin:4px 0}}
.kpi-card .label{{font-size:11px;color:#888}}
.summary{{background:#f8f9fa;border-left:4px solid #3498db;padding:12px 16px;border-radius:6px;line-height:1.8;font-size:13px;margin-bottom:16px}}
.summary p{{margin:4px 0}}
.section{{background:#fff;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.07);margin-bottom:16px;padding:16px}}
.section h2{{font-size:16px;color:#1a5276;border-left:4px solid #3498db;padding-left:10px;margin-bottom:10px}}
.chart{{width:100%}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#1a5276;color:#fff;padding:7px 6px;text-align:center;font-weight:600}}
td{{padding:5px 6px;border-bottom:1px solid #eee;text-align:center}}
tr:hover td{{background:#f0f4f8}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.tbw{{max-height:65vh;overflow-y:auto}}
.footer{{text-align:center;color:#999;font-size:11px;padding:14px}}
</style></head>
<body>
<div class="header">
<h1>🏭 生产日报（PG 版）</h1>
<div class="meta">数据源: Oracle GET_VALID_WOW → plan_daily_detail @ 10.2.20.127 · 生产日期 {date_show}（前一日白班+夜班）· 生成 {now}</div>
</div>
<div class="container">

<div class="kpi-grid">
<div class="kpi-card"><div class="label">总产线</div><div class="num" style="color:#3498db">{total_lines}</div></div>
<div class="kpi-card"><div class="label">有产出产线</div><div class="num" style="color:#27ae60">{active_lines}</div></div>
<div class="kpi-card"><div class="label">总计划量</div><div class="num" style="color:#f39c12">{total_plan:,}</div></div>
<div class="kpi-card"><div class="label">总实际产出</div><div class="num" style="color:#2980b9">{total_actual:,}</div></div>
<div class="kpi-card"><div class="label">综合达成率</div><div class="num" style="color:#8e44ad">{ach_all:.1f}%</div></div>
<div class="kpi-card"><div class="label">空闲产线</div><div class="num" style="color:#e74c3c">{idle}</div></div>
</div>

<div class="summary">{summary}</div>

{lag_section}

<div class="grid-2">
<div class="section"><h2>📦 产线状态分布</h2><img class="chart" src="data:image/png;base64,{c1}"></div>
<div class="section"><h2>☀️🌙 白班/夜班对比（按部门）</h2><img class="chart" src="data:image/png;base64,{c3}">
<table style="margin-top:10px"><thead><tr><th>部门</th><th>班次</th><th>计划</th><th>实际</th><th>达成率</th></tr></thead>
<tbody>{shift_tbl}</tbody></table></div>
</div>

<div class="section"><h2>🏭 部门对比</h2><img class="chart" src="data:image/png;base64,{c2}"></div>

<div class="section"><h2>🏆 TOP 15 产线达成率</h2><img class="chart" src="data:image/png;base64,{c4}"></div>

<div class="section"><h2>📋 产线明细（{len(line_rows)} 条有产出，按达成率降序）</h2>
<div class="tbw"><table>
<thead><tr><th>产线</th><th>工单</th><th>机种</th><th>客户</th><th>班次</th><th>计划</th><th>实际</th><th>达成率</th></tr></thead>
<tbody>{tbl}</tbody></table></div></div>

<div class="section"><h2>🔍 状态分布明细</h2>
<table><thead><tr><th>状态</th><th>产线数</th><th>实际产出</th></tr></thead>
<tbody>{status_tbl}</tbody></table></div>

</div>
<div class="footer">生产日报 PG 版 · 自动生成</div>
</body></html>'''

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = OUT / f"生产日报PG_{date_label}_{ts.split('_')[1]}.html"
    out.write_text(html, encoding='utf-8')
    print(f"✅ {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == '__main__':
    main()

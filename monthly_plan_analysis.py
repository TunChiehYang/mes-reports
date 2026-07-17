#!/usr/bin/env python3
"""
7天周计划 vs 日计划/实际产出 对比分析脚本
每天 8~18 点运行，读取最新月计划 CSV 和日报 CSV，生成 HTML 分析报告
仅取今天起往后 7 天的计划数据；风险按机种判断
输出到 D:\outputHTML\月计划分析_YYYYMMDD_HHMM.html
"""

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import base64
import io
import re
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
import glob

# ============ 配置 ============
MONTH_PLAN_DIR = Path("/mnt/d/ShareExport/output/V_MONTH_PLAN")
DAILY_REPORT_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
OUTPUT_DIR = Path("/mnt/d/outputHTML")
PLAN_ENCODING = "utf-8-sig"    # 月计划用 UTF-8 BOM
DAILY_ENCODING = "gbk"         # 日报用 GBK

# 中文字体
FONT_CANDIDATES = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei', 'Microsoft YaHei']
CHINESE_FONT = None
for fname in FONT_CANDIDATES:
    if fname in {f.name for f in fm.fontManager.ttflist}:
        CHINESE_FONT = fname
        break
if CHINESE_FONT:
    plt.rcParams['font.family'] = CHINESE_FONT
plt.rcParams['axes.unicode_minus'] = False

# ============ 部门分类 ============

def get_dept(line_id):
    """产线 → (部门, 课别)"""
    line = str(line_id).strip().upper()
    # 制造一部 - 冲压一课
    if re.match(r'^NA0[1-9]$', line): return ("制造一部", "冲压一课")
    if re.match(r'^NA(19|20|21)$', line): return ("制造一部", "冲压一课")
    if re.match(r'^NB0[1-5]$', line): return ("制造一部", "冲压一课")
    if line == "NB26": return ("制造一部", "冲压一课")
    # 制造一部 - 冲压二课
    if re.match(r'^NA1[0-8]$', line): return ("制造一部", "冲压二课")
    if re.match(r'^NB0[6-9]$|^NB10$', line): return ("制造一部", "冲压二课")
    # 制造一部 - 冲压三课
    if re.match(r'^NA(2[3-9]|3[0-2])$', line): return ("制造一部", "冲压三课")
    if re.match(r'^NB(1[1-9]|2[0-5])$', line): return ("制造一部", "冲压三课")
    # 制造二部 - 清洗一课
    if re.match(r'^NQ(10[1-9]|11[0-5])$', line): return ("制造二部", "清洗一课")
    if re.match(r'^NQ(30[1-9]|310)$', line): return ("制造二部", "清洗一课")
    # 制造二部 - 清洗二课
    if re.match(r'^NQ(20[1-9]|2[1-2][0-9])$', line): return ("制造二部", "清洗二课")
    # 制造二部 - 清洗三课
    if re.match(r'^NQ(40[1-9]|41[0-2])$', line): return ("制造二部", "清洗三课")
    if re.match(r'^NQ(50[1-9]|51[0-2])$', line): return ("制造二部", "清洗三课")
    return ("未分类", "未分类")


DEPTS = ["制造一部", "制造二部"]
KES_ORDER = {
    "制造一部": ["冲压一课", "冲压二课", "冲压三课"],
    "制造二部": ["清洗一课", "清洗二课", "清洗三课"],
}

# ============ 工具函数 ============

def find_latest_plan():
    """找最新的月计划 CSV"""
    files = sorted(MONTH_PLAN_DIR.glob("V_MONTH_PLAN_*.csv"), reverse=True)
    return files[0] if files else None

def find_latest_daily():
    """找最新的日报 CSV"""
    files = sorted(DAILY_REPORT_DIR.glob("V_PLAN_ACTUAL_SUMMARY_*.csv"), reverse=True)
    return files[0] if files else None

def fig_to_base64(fig):
    """matplotlib figure → base64 PNG"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64

def parse_ach(val):
    """解析达成率字符串"""
    if pd.isna(val):
        return 0.0
    s = str(val).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def format_qty(n):
    """格式化数量"""
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"

# ============ 数据加载 ============

def load_month_plan(filepath, today=None):
    """加载月计划 CSV，仅取 today ~ today+6 共 7 天 → {line_id: {total_qty, wos: set, models: set, customers: set, dates: list}}"""
    if today is None:
        today = date.today()
    end_date = today + timedelta(days=6)
    
    df = pd.read_csv(filepath, encoding=PLAN_ENCODING)
    df.columns = [c.strip().strip('"') for c in df.columns]
    df['RUNCARD_QTY'] = pd.to_numeric(df['RUNCARD_QTY'], errors='coerce').fillna(0).astype(int)
    
    # 解析日期列
    df['YMD_DATE'] = pd.to_datetime(df['YMD'], format='%Y/%m/%d', errors='coerce')
    # 仅取今天起的 7 天
    df7 = df[(df['YMD_DATE'] >= pd.Timestamp(today)) & (df['YMD_DATE'] <= pd.Timestamp(end_date))].copy()
    
    print(f"  月计划原始 {len(df)} 条 → 7天窗口({today}~{end_date}) {len(df7)} 条, {df7['RUNCARD_QTY'].sum():,} pcs")

    plan = {}
    for _, row in df7.iterrows():
        line = str(row['LINE_ID']).strip()
        qty = int(row['RUNCARD_QTY'])
        if line not in plan:
            plan[line] = {"total_qty": 0, "wos": set(), "models": set(), "customers": set(), "dates": []}
        plan[line]["total_qty"] += qty
        plan[line]["wos"].add(str(row.get('WO_ID', '')))
        plan[line]["models"].add(str(row.get('MODEL_NO', '')))
        plan[line]["customers"].add(str(row.get('CUSTOMER_NO', '')))
        plan[line]["dates"].append(str(row.get('YMD', '')))

    return plan, df7

def load_daily_report(filepath):
    """加载日报 CSV → {line_id: {plan_qty, auto_qty, ach, models}}
    
    日计划量取所有行(含无生产)；实际产出仅取 NOTE=正常
    如果当天无正常产出数据，尝试加载前一天晚间报告作为实际参考
    """
    df = pd.read_csv(filepath, encoding=DAILY_ENCODING)
    
    # 所有行用于日计划统计
    df['PLANQTY'] = pd.to_numeric(df['PLANQTY'], errors='coerce').fillna(0).astype(int)
    df['AUTOQTY'] = pd.to_numeric(df['AUTOQTY'], errors='coerce').fillna(0).astype(int)
    
    # 正常行用于实际产出
    df_normal = df[df['NOTE'].str.strip() == '正常'].copy()
    
    daily = {}
    
    # 日计划：所有行
    for _, row in df.iterrows():
        line = str(row['LINE_ID']).strip()
        if line not in daily:
            daily[line] = {"plan_qty": 0, "auto_qty": 0, "ach_list": [], "models": set()}
        daily[line]["plan_qty"] += int(row['PLANQTY'])
    
    # 实际产出：仅正常行
    for _, row in df_normal.iterrows():
        line = str(row['LINE_ID']).strip()
        if line not in daily:
            daily[line] = {"plan_qty": 0, "auto_qty": 0, "ach_list": [], "models": set()}
        daily[line]["auto_qty"] += int(row['AUTOQTY'])
        ach_val = parse_ach(row['ACH'])
        if ach_val > 0:
            daily[line]["ach_list"].append(ach_val)
        models = str(row.get('ACTUAL_MODEL_LIST', '')).strip()
        if models:
            for m in models.split('/'):
                daily[line]["models"].add(m.strip())

    # 如果没有正常产出，尝试用前一天晚间报告
    has_actual = any(d["auto_qty"] > 0 for d in daily.values())
    if not has_actual:
        # 找前一天 20:30 的报告
        yesterday = datetime.now() - timedelta(days=1)
        y_str = yesterday.strftime("%Y%m%d")
        prev_files = sorted(DAILY_REPORT_DIR.glob(f"V_PLAN_ACTUAL_SUMMARY_{y_str}_20*.csv"), reverse=True)
        if prev_files:
            print(f"  当天无产出，加载前日晚间报告: {prev_files[0].name}")
            prev_daily, _ = load_daily_report(prev_files[0])
            for line, pd_data in prev_daily.items():
                if line not in daily:
                    daily[line] = {"plan_qty": 0, "auto_qty": 0, "ach_list": [], "models": set()}
                daily[line]["prev_auto_qty"] = pd_data.get("auto_qty", 0)

    # 计算平均达成率
    for line in daily:
        ach_list = daily[line]["ach_list"]
        daily[line]["avg_ach"] = sum(ach_list) / len(ach_list) if ach_list else 0

    return daily, df

# ============ 图表生成 ============

def chart_dept_comparison(week_plan, daily_report):
    """部门级周计划 vs 日计划/实际 对比图"""
    dept_data = {}
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            key = (dept, kes)
            dept_data[key] = {"week_plan": 0, "daily_plan": 0, "daily_actual": 0, "line_count": 0}

    # 汇总周计划
    for line, wp in week_plan.items():
        dept, kes = get_dept(line)
        if (dept, kes) in dept_data:
            dept_data[(dept, kes)]["week_plan"] += wp["total_qty"]
            dept_data[(dept, kes)]["line_count"] += 1

    # 汇总日报
    for line, dr in daily_report.items():
        dept, kes = get_dept(line)
        if (dept, kes) in dept_data:
            dept_data[(dept, kes)]["daily_plan"] += dr["plan_qty"]
            dept_data[(dept, kes)]["daily_actual"] += dr["auto_qty"]

    labels = []
    week_vals = []
    daily_plan_vals = []
    daily_actual_vals = []
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            d = dept_data[(dept, kes)]
            if d["line_count"] > 0:
                labels.append(f"{kes}\\n({d['line_count']}线)")
                week_vals.append(d["week_plan"])
                daily_plan_vals.append(d["daily_plan"])
                daily_actual_vals.append(d["daily_actual"])

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(labels))
    width = 0.25

    bars1 = ax.bar(x - width, week_vals, width, label='周计划量', color='#3498db', alpha=0.9)
    bars2 = ax.bar(x, daily_plan_vals, width, label='日计划量', color='#f39c12', alpha=0.9)
    bars3 = ax.bar(x + width, daily_actual_vals, width, label='日实际产出', color='#27ae60', alpha=0.9)

    for bar, val in zip(bars1, week_vals):
        if val >= 10000:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500,
                    f'{val/10000:.1f}万', ha='center', va='bottom', fontsize=8)
        elif val > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500,
                    f'{val:,}', ha='center', va='bottom', fontsize=8)

    ax.set_ylabel('数量 (pcs)')
    ax.set_title('周计划 vs 日计划/实际产出 — 课别对比', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    return fig_to_base64(fig)

def chart_risk_models(week_plan, daily_report, plan_df):
    """按机种风险评估：7天计划 vs 日产能×7天。当天无产出时回退前日晚间"""
    # 汇总机种的7天计划
    model_plan = {}
    for line, wp in week_plan.items():
        for m in wp["models"]:
            m = m.strip()
            if not m:
                continue
            if m not in model_plan:
                model_plan[m] = {"total_qty": 0, "lines": set()}
            model_plan[m]["total_qty"] += wp["total_qty"]
            model_plan[m]["lines"].add(line)
    
    # 产线日产能（实际产出，不含0）
    line_cap = {}
    for line, dr in daily_report.items():
        auto = dr.get("auto_qty", 0)
        if auto == 0:
            auto = dr.get("prev_auto_qty", 0)
        if auto > 0:
            line_cap[line] = auto
    
    # 按机种评估：7天计划 vs 日产能×7
    risk_models = []
    for model, mp in model_plan.items():
        lines = mp["lines"]
        daily_cap = sum(line_cap.get(l, 0) for l in lines)
        cap_7day = daily_cap * 7
        gap = mp["total_qty"] - cap_7day
        
        if gap > 0 or daily_cap == 0:
            note = "无产能" if daily_cap == 0 else f"缺口{gap/10000:.1f}万"
            risk_models.append((model[:30], mp["total_qty"], daily_cap, cap_7day, gap, note))
    
    risk_models.sort(key=lambda x: x[4], reverse=True)
    risk_models = risk_models[:12]
    
    if not risk_models:
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(0.5, 0.5, '无风险机种（7天计划均不超产能）', ha='center', va='center',
                fontsize=14, color='#888', transform=ax.transAxes)
        ax.set_title('[风险] 机种：7天计划 vs 推算产能(日产能×7天)', fontsize=14, fontweight='bold')
        ax.set_xticks([]); ax.set_yticks([])
        fig.tight_layout()
        return fig_to_base64(fig), len(risk_models)
    
    fig, ax = plt.subplots(figsize=(12, 6))
    labels = [r[0] for r in risk_models]
    plan_vals = [r[1] for r in risk_models]
    cap_vals = [r[3] for r in risk_models]
    
    x = np.arange(len(labels))
    width = 0.35
    
    ax.bar(x - width/2, plan_vals, width, label='7天计划', color='#e74c3c', alpha=0.85)
    ax.bar(x + width/2, cap_vals, width, label='推算产能(日产能×7)', color='#95a5a6', alpha=0.85)
    
    for i, (model, plan, daily, cap, gap, note) in enumerate(risk_models):
        ax.text(i, max(plan, cap) + 500, note, ha='center', fontsize=7,
                color='#e74c3c', fontweight='bold')
    
    ax.set_ylabel('数量 (pcs)')
    ax.set_title('[风险] 机种：7天计划 vs 推算产能(日产能×7天)', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8, rotation=30, ha='right')
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    return fig_to_base64(fig), len(risk_models)

def chart_daily_distribution(plan_df):
    """月计划日期分布"""
    date_counts = plan_df.groupby('YMD')['RUNCARD_QTY'].sum().sort_index()

    fig, ax = plt.subplots(figsize=(14, 5))
    dates = date_counts.index.tolist()
    values = date_counts.values.tolist()

    colors = ['#3498db' if i < 7 else '#f39c12' if i < 14 else '#95a5a6' for i in range(len(dates))]
    bars = ax.bar(range(len(dates)), values, color=colors, edgecolor='white', linewidth=0.5)

    # 只在量大的柱上标数值
    for i, (bar, val) in enumerate(zip(bars, values)):
        if val > 30000:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500,
                    f'{val/10000:.1f}万', ha='center', fontsize=7)

    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels([d[-5:] for d in dates], rotation=45, ha='right', fontsize=8)
    ax.set_ylabel('计划量 (pcs)')
    ax.set_title('月计划日别分布 (蓝=第1周 橙=第2周 灰=第3周后)', fontsize=13, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    fig.tight_layout()
    return fig_to_base64(fig)


# ============ HTML 报表生成 ============

def generate_html(week_plan, daily_report, plan_df, daily_df, charts, source_info, risk_count=0):
    """生成完整 HTML 报告"""

    total_week = sum(wp["total_qty"] for wp in week_plan.values())
    total_daily_plan = sum(dr["plan_qty"] for dr in daily_report.values())
    total_daily_auto = sum(dr["auto_qty"] for dr in daily_report.values())
    daily_ach = total_daily_auto / total_daily_plan * 100 if total_daily_plan > 0 else 0
    daily_line_count = len(daily_report)

    # 部门汇总表
    dept_summary_rows = ""
    for dept in DEPTS:
        for kes in KES_ORDER[dept]:
            wp_total = 0; dp_total = 0; da_total = 0; lines_set = set()
            for line, wp in week_plan.items():
                if get_dept(line) == (dept, kes):
                    wp_total += wp["total_qty"]
                    lines_set.add(line)
            for line, dr in daily_report.items():
                if get_dept(line) == (dept, kes):
                    dp_total += dr["plan_qty"]
                    da_total += dr["auto_qty"]

            if wp_total == 0 and dp_total == 0:
                continue

            ach_val = f"{da_total/dp_total*100:.1f}%" if dp_total > 0 else "—"
            row_class = ""
            if dp_total > 0 and da_total/dp_total < 0.6:
                row_class = 'style="background:#fff5f5"'
            dept_summary_rows += f"""<tr {row_class}>
                <td>{dept}</td><td>{kes}</td><td>{len(lines_set)}</td>
                <td class="num">{wp_total:,}</td>
                <td class="num">{dp_total:,}</td>
                <td class="num">{da_total:,}</td>
                <td class="ach">{ach_val}</td>
            </tr>"""

    # 产线明细表
    line_detail_rows = ""
    all_lines = set(list(week_plan.keys()) + list(daily_report.keys()))
    for line in sorted(all_lines):
        wp = week_plan.get(line, {"total_qty": 0, "wos": set(), "models": set()})
        dr = daily_report.get(line, {"plan_qty": 0, "auto_qty": 0, "avg_ach": 0, "prev_auto_qty": 0})
        dept, kes = get_dept(line)

        wp_qty = wp["total_qty"]
        dp_qty = dr["plan_qty"]
        da_qty = dr["auto_qty"]
        ach = dr["avg_ach"]
        
        # 风险：7天计划 vs 日产能
        risk_auto = da_qty if da_qty > 0 else dr.get("prev_auto_qty", 0)

        risk = ""
        if wp_qty > 0 and risk_auto > 0:
            est_days = wp_qty / risk_auto if risk_auto > 0 else 0
            if est_days > 7:
                risk = '<span style="color:#e74c3c;font-weight:bold">超产能</span>'
            elif est_days > 5:
                risk = '<span style="color:#f39c12;font-weight:bold">偏紧</span>'
            else:
                risk = '<span style="color:#27ae60">正常</span>'
        elif wp_qty > 0 and risk_auto == 0:
            risk = '<span style="color:#c0392b;font-weight:bold">无产出</span>'

        models_str = " / ".join(sorted(wp["models"])[:3]) if wp["models"] else "—"

        ach_str = f"{ach:.1f}%" if ach > 0 else "—"
        row_style = ""
        if wp_qty > 0 and da_qty == 0:
            row_style = 'style="background:#ffeaea"'
        elif dp_qty > 0 and ach > 0 and ach < 50:
            row_style = 'style="background:#fff8e1"'

        line_detail_rows += f"""<tr {row_style}>
            <td>{line}</td><td>{dept}-{kes}</td><td>{risk}</td>
            <td class="num">{wp_qty:,}</td>
            <td class="num">{dp_qty:,}</td>
            <td class="num">{da_qty:,}</td>
            <td class="ach">{ach_str}</td>
            <td class="model">{models_str}</td>
        </tr>"""

    # 客户分布 (周计划)
    cust_rows = ""
    cust_qty = plan_df.groupby('CUSTOMER_NO')['RUNCARD_QTY'].sum().sort_values(ascending=False).head(10)
    for cust, qty in cust_qty.items():
        pct = qty / total_week * 100 if total_week else 0
        cust_rows += f"<tr><td>{cust}</td><td class='num'>{qty:,}</td><td class='num'>{pct:.1f}%</td></tr>"

    # 机型 Top 10 (周计划)
    model_rows = ""
    model_qty = plan_df.groupby('MODEL_NO')['RUNCARD_QTY'].sum().sort_values(ascending=False).head(10)
    for model, qty in model_qty.items():
        pct = qty / total_week * 100 if total_week else 0
        short_model = model[:50]
        model_rows += f"<tr><td title='{model}'>{short_model}</td><td class='num'>{qty:,}</td><td class='num'>{pct:.1f}%</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>7天周计划分析报告</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'WenQuanYi Zen Hei', 'Microsoft YaHei', -apple-system, sans-serif;
        background: #f0f2f5;
        color: #333;
        padding: 20px;
        -webkit-user-select: text;
        user-select: text;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    .header {{
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        color: white;
        padding: 30px 40px;
        border-radius: 16px;
        margin-bottom: 24px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
    }}
    .header h1 {{ font-size: 26px; margin-bottom: 6px; }}
    .header .meta {{ font-size: 13px; opacity: 0.75; margin-top: 8px; }}
    .kpi-row {{
        display: flex;
        gap: 16px;
        margin-bottom: 24px;
    }}
    .kpi-card {{
        flex: 1;
        background: white;
        border-radius: 12px;
        padding: 20px 24px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        text-align: center;
    }}
    .kpi-card .label {{ font-size: 13px; color: #888; margin-bottom: 4px; }}
    .kpi-card .value {{ font-size: 28px; font-weight: 700; }}
    .kpi-card .sub {{ font-size: 12px; color: #aaa; margin-top: 2px; }}
    .kpi-card.blue .value {{ color: #3498db; }}
    .kpi-card.green .value {{ color: #27ae60; }}
    .kpi-card.orange .value {{ color: #f39c12; }}
    .kpi-card.red .value {{ color: #e74c3c; }}
    .section {{
        background: white;
        border-radius: 12px;
        padding: 24px 28px;
        margin-bottom: 20px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }}
    .section h2 {{
        font-size: 18px;
        color: #1a1a2e;
        margin-bottom: 16px;
        padding-bottom: 10px;
        border-bottom: 2px solid #3498db;
    }}
    .chart-img {{
        max-width: 100%;
        height: auto;
        border-radius: 8px;
        margin: 12px 0;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }}
    thead th {{
        background: #f8f9fa;
        padding: 10px 12px;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid #dee2e6;
        white-space: nowrap;
        position: sticky;
        top: 0;
    }}
    tbody td {{
        padding: 8px 12px;
        border-bottom: 1px solid #f1f3f5;
    }}
    tbody tr:hover {{ background: #f8f9ff; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .ach {{ text-align: right; font-weight: 600; }}
    .model {{ font-size: 12px; color: #666; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .table-wrap {{ max-height: 600px; overflow-y: auto; }}
    .grid-2 {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
    }}
    @media (max-width: 900px) {{
        .grid-2 {{ grid-template-columns: 1fr; }}
        .kpi-row {{ flex-wrap: wrap; }}
    }}
    .note {{ font-size: 12px; color: #888; margin-top: 8px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
    <h1>📊 7天周计划 vs 日计划分析报告</h1>
    <div class="meta">
        生成时间: {source_info['gen_time']} &nbsp;|&nbsp;
        周计划: {source_info['plan_file']} &nbsp;|&nbsp;
        日报: {source_info['daily_file']}
    </div>
</div>

<!-- KPI 卡片 -->
<div class="kpi-row">
    <div class="kpi-card blue">
        <div class="label">📋 7天周计划总量</div>
        <div class="value">{format_qty(total_week)}</div>
        <div class="sub">{len(week_plan)} 条产线</div>
    </div>
    <div class="kpi-card orange">
        <div class="label">📅 今日日计划</div>
        <div class="value">{format_qty(total_daily_plan)}</div>
        <div class="sub">{daily_line_count} 条产线有产出</div>
    </div>
    <div class="kpi-card green">
        <div class="label">✅ 今日实际产出</div>
        <div class="value">{format_qty(total_daily_auto)}</div>
        <div class="sub">达成率 {daily_ach:.1f}%</div>
    </div>
    <div class="kpi-card red">
        <div class="label">[!] 风险机种</div>
        <div class="value">{risk_count}</div>
        <div class="sub">7天计划 &gt; 产能</div>
    </div>
</div>

<!-- 图表区域 -->
<div class="section">
    <h2>📈 课别级：周计划 vs 日计划/实际</h2>
    <img class="chart-img" src="data:image/png;base64,{charts['dept_comparison']}" alt="课别对比">
</div>

<div class="grid-2">
    <div class="section">
        <h2>🗓 周计划日别分布</h2>
        <img class="chart-img" src="data:image/png;base64,{charts['daily_dist']}" alt="日别分布">
    </div>
    <div class="section">
        <h2>⚠ 风险机种（7天计划 vs 日产能×7）</h2>
        <img class="chart-img" src="data:image/png;base64,{charts['risk_models']}" alt="风险机种">
    </div>
</div>

<!-- 部门汇总 -->
<div class="section">
    <h2>📊 部门/课别 汇总</h2>
    <table>
        <thead>
            <tr><th>部门</th><th>课别</th><th>产线</th><th>周计划</th><th>日计划</th><th>日实际</th><th>达成率</th></tr>
        </thead>
        <tbody>
            {dept_summary_rows}
        </tbody>
    </table>
</div>

<!-- 产线明细 -->
<div class="section">
    <h2>🔍 产线明细（7天计划 vs 今日产出）</h2>
    <div class="table-wrap">
    <table>
        <thead>
            <tr><th>产线</th><th>课别</th><th>风险</th><th>周计划</th><th>日计划</th><th>日实际</th><th>达成率</th><th>主要机型</th></tr>
        </thead>
        <tbody>
            {line_detail_rows}
        </tbody>
    </table>
    </div>
</div>

<!-- 客户 & 机型 -->
<div class="grid-2">
    <div class="section">
        <h2>🏢 周计划 Top 10 客户</h2>
        <table>
            <thead><tr><th>客户</th><th>计划量</th><th>占比</th></tr></thead>
            <tbody>{cust_rows}</tbody>
        </table>
    </div>
    <div class="section">
        <h2>📦 周计划 Top 10 机型</h2>
        <table>
            <thead><tr><th>机型</th><th>计划量</th><th>占比</th></tr></thead>
            <tbody>{model_rows}</tbody>
        </table>
    </div>
</div>

<div class="note">
    注：仅取月计划中今天起 7 天数据；日计划/实际来自当天最新日报（仅 NOTE=正常）；风险：7天计划 / 日产能 &gt; 7天=超产能，&gt;5天=偏紧；无产出则日产能为0。
</div>

</div>
</body>
</html>"""

    return html


# ============ 主流程 ============

def main():
    print("=" * 60)
    print("  7天周计划 vs 日计划 对比分析")
    print("=" * 60)

    # 1. 找文件
    plan_file = find_latest_plan()
    daily_file = find_latest_daily()

    if not plan_file:
        print("[ERROR] 未找到月计划 CSV")
        sys.exit(1)
    if not daily_file:
        print("[ERROR] 未找到日报 CSV")
        sys.exit(1)

    print(f"  月计划: {plan_file.name}")
    print(f"  日报:   {daily_file.name}")

    # 2. 加载数据（仅取7天）
    week_plan, plan_df = load_month_plan(plan_file)
    daily_report, daily_df = load_daily_report(daily_file)

    print(f"  周计划: {len(week_plan)} 条产线, {plan_df['RUNCARD_QTY'].sum():,} pcs")
    print(f"  日报(正常): {len(daily_report)} 条产线, 计划 {daily_df['PLANQTY'].sum():,} pcs, 实际 {daily_df['AUTOQTY'].sum():,} pcs")

    # 3. 生成图表
    print("  生成图表...")
    charts = {}
    charts['dept_comparison'] = chart_dept_comparison(week_plan, daily_report)
    risk_chart, risk_count = chart_risk_models(week_plan, daily_report, plan_df)
    charts['risk_models'] = risk_chart
    charts['daily_dist'] = chart_daily_distribution(plan_df)

    # 4. 生成 HTML
    source_info = {
        'gen_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'plan_file': plan_file.name,
        'daily_file': daily_file.name,
    }

    # 从文件名提取时间戳
    ts_match = re.search(r'(\d{8})_(\d{6})', plan_file.name)
    if ts_match:
        date_str = ts_match.group(1)
        time_str = ts_match.group(2)[:4]  # HHMM
    else:
        now = datetime.now()
        date_str = now.strftime('%Y%m%d')
        time_str = now.strftime('%H%M')

    output_name = f"月计划分析_{date_str}_{time_str}.html"
    output_path = OUTPUT_DIR / output_name

    html = generate_html(week_plan, daily_report, plan_df, daily_df, charts, source_info, risk_count)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')

    file_size = output_path.stat().st_size
    print(f"\n  ✅ 报告已生成: {output_path}")
    print(f"     大小: {file_size/1024:.0f} KB")
    print(f"     访问: http://192.168.101.152:8080/{output_name}")

    return 0

if __name__ == '__main__':
    sys.exit(main())

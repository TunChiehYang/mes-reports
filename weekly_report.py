#!/usr/bin/env python3
"""
生产周报脚本
每周一 9:30 运行，汇总上周（周一~周日）所有正常生产数据
"""

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import sys
import base64
import io
import re
from datetime import datetime, date, timedelta
from pathlib import Path

SOURCE_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
OUTPUT_DIR = Path("/mnt/d/outputHTML")
ENCODING = "gbk"

# 中文字体
FONT_CANDIDATES = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei']
CHINESE_FONT = None
for fname in FONT_CANDIDATES:
    if fname in {f.name for f in fm.fontManager.ttflist}:
        CHINESE_FONT = fname
        break
if CHINESE_FONT:
    plt.rcParams['font.family'] = CHINESE_FONT
plt.rcParams['axes.unicode_minus'] = False

# 导入日报脚本中的部门分类函数
sys.path.insert(0, str(Path(__file__).parent))
from production_report import get_dept, get_parent_dept

ALL_DEPTS = ['冲压一课', '冲压二课', '冲压三课', '清洗一课', '清洗二课', '清洗三课']
DEPT_COLORS = {'冲压一课': '#3498db', '冲压二课': '#e67e22', '冲压三课': '#9b59b6',
               '清洗一课': '#1abc9c', '清洗二课': '#2ecc71', '清洗三课': '#e74c3c'}


def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def get_week_range(target_date=None):
    """返回上周一~上周日的日期范围"""
    if target_date is None:
        target_date = date.today()
    # 本周一
    this_monday = target_date - timedelta(days=target_date.weekday())
    # 上周一 = 本周一 - 7
    last_monday = this_monday - timedelta(days=7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday


def load_week_data(week_start, week_end):
    """加载一周内所有 CSV，返回合并后的 DataFrame"""
    all_dfs = []
    current = week_start
    while current <= week_end:
        date_str = current.strftime("%Y%m%d")
        pattern = f"V_PLAN_ACTUAL_SUMMARY_{date_str}_*.csv"
        files = sorted(SOURCE_DIR.glob(pattern))
        if files:
            # 取每天最新的文件
            latest = files[-1]
            try:
                df = pd.read_csv(latest, encoding=ENCODING)
                df['数据日期'] = current.strftime('%m/%d')
                df['源文件'] = latest.name
                all_dfs.append(df)
            except Exception as e:
                print(f"  [WARN] 读取失败 {latest}: {e}")
        current += timedelta(days=1)

    if not all_dfs:
        return None, []

    combined = pd.concat(all_dfs, ignore_index=True)
    # 填充
    combined['NOTE'] = combined['NOTE'].fillna('未知')
    combined['ACTUAL_MODEL_LIST'] = combined['ACTUAL_MODEL_LIST'].fillna('')
    return combined, sorted(set(combined['数据日期']))


def parse_ach(val):
    if pd.isna(val):
        return 0.0
    try:
        return float(str(val).replace('%', '').strip())
    except:
        return 0.0


def chart_weekly_dept(df_calc):
    """周报：部门达成率对比"""
    df_calc['ACH_NUM'] = df_calc['ACH'].apply(parse_ach)
    df_calc['DEPT'] = df_calc['LINE_ID'].apply(get_dept)
    dept = df_calc.groupby('DEPT').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        LINES=('LINE_ID', 'nunique'),
        RECORDS=('PLANQTY', 'count')
    ).reset_index()
    dept['ACH'] = (dept['AUTOQTY'] / dept['PLANQTY'].replace(0, np.nan) * 100).fillna(0)
    order = {d: i for i, d in enumerate(ALL_DEPTS)}
    dept['SORT'] = dept['DEPT'].map(order)
    dept = dept.dropna(subset=['SORT']).sort_values('SORT')

    fig, axes = plt.subplots(1, 2, figsize=(16, 5.5))
    x = np.arange(len(dept))
    w = 0.35
    ax = axes[0]
    ax.bar(x - w/2, dept['PLANQTY'] / 1000, w, label='周计划量', color='#3498db', edgecolor='white')
    ax.bar(x + w/2, dept['AUTOQTY'] / 1000, w, label='周实际产出', color='#e74c3c', edgecolor='white')
    for i, (p, a) in enumerate(zip(dept['PLANQTY'], dept['AUTOQTY'])):
        ax.text(i - w/2, p/1000 + 1, f'{int(p):,}', ha='center', fontsize=7)
        ax.text(i + w/2, a/1000 + 1, f'{int(a):,}', ha='center', fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(dept['DEPT'], fontsize=9)
    ax.set_ylabel('数量 (千)', fontsize=11)
    ax.set_title('各部门 周计划/实际对比', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    if len(dept) >= 4:
        ax.axvline(x=2.5, color='#2c3e50', linestyle='-', alpha=0.3, linewidth=2)

    ax = axes[1]
    colors = [DEPT_COLORS.get(d, '#999') for d in dept['DEPT']]
    bars = ax.bar(dept['DEPT'], dept['ACH'], color=colors, edgecolor='white', width=0.5)
    for bar, ach in zip(bars, dept['ACH']):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{ach:.1f}%', ha='center', fontsize=11, fontweight='bold')
    ax.set_ylabel('周达成率 (%)', fontsize=11)
    ax.set_title('各部门 周达成率对比', fontsize=13, fontweight='bold')
    ax.axhline(y=80, color='#27ae60', linestyle='--', alpha=0.6, label='80% 目标线')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    return fig, dept


def chart_daily_trend(df_calc, dates):
    """周报：每日达成率趋势"""
    df_calc['ACH_NUM'] = df_calc['ACH'].apply(parse_ach)
    daily = df_calc.groupby('数据日期').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum')
    ).reindex(dates).fillna(0)
    daily['ACH'] = (daily['AUTOQTY'] / daily['PLANQTY'].replace(0, np.nan) * 100).fillna(0)

    fig, ax = plt.subplots(figsize=(12, 4.5))
    x = np.arange(len(daily))
    ax.bar(x - 0.15, daily['PLANQTY'] / 1000, 0.3, label='计划量(K)', color='#3498db', alpha=0.7)
    ax.bar(x + 0.15, daily['AUTOQTY'] / 1000, 0.3, label='实际产出(K)', color='#e74c3c', alpha=0.7)

    ax2 = ax.twinx()
    ax2.plot(x, daily['ACH'], 'o-', color='#2ecc71', linewidth=2, markersize=8, label='达成率')
    for i, ach in enumerate(daily['ACH']):
        if ach > 0:
            ax2.annotate(f'{ach:.1f}%', (i, ach), textcoords="offset points", xytext=(0, 10),
                        ha='center', fontsize=9, fontweight='bold', color='#27ae60')

    ax.set_xticks(x)
    ax.set_xticklabels(daily.index, fontsize=10)
    ax.set_ylabel('数量 (千)', fontsize=11)
    ax2.set_ylabel('达成率 (%)', fontsize=11, color='#27ae60')
    ax.set_title('每日达成率趋势', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    ax2.legend(loc='upper right', fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    ax.set_ylim(bottom=0)
    ax2.set_ylim(bottom=0)
    fig.tight_layout()
    return fig


def generate_weekly_html(df, df_calc, charts, dept_data, week_start, week_end, dates):
    """生成周报 HTML"""
    total_plan = int(df_calc['PLANQTY'].sum())
    total_actual = int(df_calc['AUTOQTY'].sum())
    overall_ach = (total_actual / total_plan * 100) if total_plan > 0 else 0

    # 产线周汇总
    line_week = df_calc.groupby(['LINE_ID', '数据日期']).agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
    ).reset_index()
    line_total = line_week.groupby('LINE_ID').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        DAYS=('数据日期', 'nunique')
    ).reset_index()
    line_total['ACH'] = (line_total['AUTOQTY'] / line_total['PLANQTY'].replace(0, np.nan) * 100).fillna(0)
    line_total = line_total[line_total['PLANQTY'] > 0].sort_values('ACH', ascending=False)
    line_total['DEPT'] = line_total['LINE_ID'].apply(get_dept)

    # 部门汇总表
    dept_rows = ""
    for _, r in dept_data.iterrows():
        ach_c = '#27ae60' if r['ACH'] >= 80 else '#f39c12' if r['ACH'] >= 50 else '#e74c3c'
        dept_rows += f"""<tr>
            <td style="font-weight:bold">{r['DEPT']}</td>
            <td>{int(r['LINES'])}</td>
            <td>{int(r['RECORDS'])}</td>
            <td>{int(r['PLANQTY']):,}</td>
            <td>{int(r['AUTOQTY']):,}</td>
            <td style="color:{ach_c};font-weight:bold">{r['ACH']:.1f}%</td>
        </tr>"""

    # 各部门 Top 3 / Bottom 3
    dept_tables_html = ""
    current_parent = None
    for dept_name in ALL_DEPTS:
        parent = get_parent_dept(dept_name)
        if parent != current_parent:
            current_parent = parent
            dept_tables_html += f"""
    <h2 style="color:#2c3e50;margin:32px 0 16px 0;padding:12px 20px;background:linear-gradient(135deg,#ecf0f1,#dfe6e9);border-radius:8px;font-size:18px;">🏭 {parent}</h2>"""

        d_lines = line_total[line_total['DEPT'] == dept_name]
        top3 = d_lines.head(3)
        bot3 = d_lines.tail(3)
        dp = int(d_lines['PLANQTY'].sum()) if len(d_lines) > 0 else 0
        da = int(d_lines['AUTOQTY'].sum()) if len(d_lines) > 0 else 0
        dach = (da / dp * 100) if dp > 0 else 0

        top_html = ''.join(f'<tr><td>{r["LINE_ID"]}</td><td>{int(r["PLANQTY"]):,}</td><td>{int(r["AUTOQTY"]):,}</td><td style="color:#27ae60;font-weight:bold">{r["ACH"]:.1f}%</td></tr>' for _, r in top3.iterrows()) if len(top3) > 0 else '<tr><td colspan="4" style="color:#95a5a6">无数据</td></tr>'
        bot_html = ''.join(f'<tr><td>{r["LINE_ID"]}</td><td>{int(r["PLANQTY"]):,}</td><td>{int(r["AUTOQTY"]):,}</td><td style="color:#e74c3c;font-weight:bold">{r["ACH"]:.1f}%</td></tr>' for _, r in bot3.iterrows()) if len(bot3) > 0 else '<tr><td colspan="4" style="color:#95a5a6">无数据</td></tr>'

        color = DEPT_COLORS.get(dept_name, '#999')
        dept_tables_html += f"""
    <h3 style="color:#2c3e50;margin:16px 0 8px 0;padding-bottom:4px;border-bottom:2px solid {color};">{dept_name}（{len(d_lines)}条产线，周达成率 {dach:.1f}%）</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <div class="table-section"><h3 style="margin-bottom:8px;color:#27ae60">🏆 周 Top 3</h3>
            <table><tr><th>产线</th><th>周计划</th><th>周产出</th><th>达成率</th></tr>{top_html}</table></div>
        <div class="table-section"><h3 style="margin-bottom:8px;color:#e74c3c">⚠️ 周 Bottom 3</h3>
            <table><tr><th>产线</th><th>周计划</th><th>周产出</th><th>达成率</th></tr>{bot_html}</table></div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>生产周报 - {week_start.strftime('%Y/%m/%d')} ~ {week_end.strftime('%Y/%m/%d')}</title>
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:-apple-system,'Microsoft YaHei',sans-serif; background:linear-gradient(135deg,#f5f7fa,#c3cfe2); min-height:100vh; padding:20px; -webkit-user-select:text; user-select:text; }}
    .container {{ max-width:1300px; margin:0 auto; }}
    .header {{ background:linear-gradient(135deg,#1a5276,#2e86c1); color:white; padding:30px 40px; border-radius:16px; margin-bottom:24px; box-shadow:0 8px 32px rgba(0,0,0,0.15); }}
    .header h1 {{ font-size:28px; margin-bottom:6px; }}
    .header .meta {{ font-size:14px; opacity:0.85; }}
    .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:24px; }}
    .kpi-card {{ background:white; border-radius:12px; padding:20px; box-shadow:0 4px 16px rgba(0,0,0,0.08); text-align:center; }}
    .kpi-card .label {{ font-size:13px; color:#7f8c8d; margin-bottom:6px; }}
    .kpi-card .value {{ font-size:30px; font-weight:bold; }}
    .kpi-card .sub {{ font-size:12px; color:#95a5a6; margin-top:4px; }}
    .highlight-box {{ background:linear-gradient(135deg,#fff9e6,#ffeaa7); border-left:4px solid #f39c12; padding:16px 20px; border-radius:0 8px 8px 0; margin-bottom:20px; font-size:14px; line-height:1.8; }}
    .chart-section {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }}
    .chart-card {{ background:white; border-radius:12px; padding:20px; box-shadow:0 4px 16px rgba(0,0,0,0.08); }}
    .chart-card.full {{ grid-column:1/-1; }}
    .chart-card img {{ width:100%; border-radius:8px; }}
    .chart-card h3 {{ font-size:16px; color:#2c3e50; margin-bottom:16px; padding-bottom:8px; border-bottom:2px solid #ecf0f1; }}
    .table-section {{ background:white; border-radius:12px; padding:20px; box-shadow:0 4px 16px rgba(0,0,0,0.08); }}
    table {{ width:100%; border-collapse:collapse; }}
    th {{ background:#2c3e50; color:white; padding:10px 14px; text-align:left; font-size:13px; }}
    td {{ padding:9px 14px; border-bottom:1px solid #ecf0f1; font-size:13px; }}
    tr:hover {{ background:#f8f9fa; }}
    .footer {{ text-align:center; color:#95a5a6; font-size:12px; padding:20px; }}
    @media(max-width:900px){{ .chart-section{{grid-template-columns:1fr;}} }}
</style>
<script>
(function(){{
    document.addEventListener('keydown',function(e){{
        if((e.ctrlKey||e.metaKey)&&e.key==='c'){{e.stopPropagation();}}
        if((e.ctrlKey||e.metaKey)&&e.key==='a'){{e.stopPropagation();}}
    }},true);
    document.addEventListener('copy',function(e){{e.stopPropagation();}},true);
    document.addEventListener('selectstart',function(e){{e.stopPropagation();}},true);
}})();
</script>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 生产周报</h1>
        <div class="meta">统计周期：{week_start.strftime('%Y/%m/%d')}（周一）~ {week_end.strftime('%Y/%m/%d')}（周日）&nbsp;|&nbsp;数据天数：{len(dates)}天 &nbsp;|&nbsp;生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
    </div>

    <div class="kpi-grid">
        <div class="kpi-card"><div class="label">📋 周计划总量</div><div class="value" style="color:#3498db">{total_plan:,}</div><div class="sub">件</div></div>
        <div class="kpi-card"><div class="label">✅ 周实际产出</div><div class="value" style="color:#27ae60">{total_actual:,}</div><div class="sub">件</div></div>
        <div class="kpi-card"><div class="label">📈 周达成率</div><div class="value" style="color:{'#27ae60' if overall_ach>=80 else '#f39c12' if overall_ach>=50 else '#e74c3c'}">{overall_ach:.1f}%</div><div class="sub">{'✅ 达标' if overall_ach>=80 else '⚠️ 未达标'}</div></div>
        <div class="kpi-card"><div class="label">🏭 产线数</div><div class="value" style="color:#9b59b6">{df_calc['LINE_ID'].nunique()}</div><div class="sub">条产线正常生产</div></div>
        <div class="kpi-card"><div class="label">📅 有效天数</div><div class="value" style="color:#e67e22">{len(dates)}</div><div class="sub">天有生产数据</div></div>
    </div>

    <div class="highlight-box">
        <strong>📝 周报摘要：</strong>
        {week_start.strftime('%m/%d')}~{week_end.strftime('%m/%d')} 共 <strong>{len(dates)}</strong> 个工作日，
        <strong>{df_calc['LINE_ID'].nunique()}</strong> 条产线正常生产，
        周计划 <strong>{total_plan:,}</strong> 件，周产出 <strong>{total_actual:,}</strong> 件，达成率 <strong>{overall_ach:.1f}%</strong>。
    </div>

    <div class="chart-section">
        <div class="chart-card full"><h3>📈 每日达成率趋势</h3><img src="data:image/png;base64,{charts['daily_trend']}"></div>
    </div>

    <div class="chart-section">
        <div class="chart-card full"><h3>🏢 各部门周达成率对比</h3><img src="data:image/png;base64,{charts['weekly_dept']}"></div>
    </div>

    <div class="table-section" style="margin-bottom:24px;">
        <h3 style="margin-bottom:12px;color:#2c3e50">🏢 部门周汇总</h3>
        <table>
            <tr><th>部门</th><th>产线数</th><th>记录数</th><th>周计划</th><th>周产出</th><th>周达成率</th></tr>
            {dept_rows}
        </table>
    </div>

    {dept_tables_html}

    <div class="footer">由 Hermes Agent 自动生成 &nbsp;|&nbsp; {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
</div>
</body>
</html>"""
    return html


def main():
    week_start, week_end = get_week_range()
    print(f"[INFO] 统计周期: {week_start}（周一） ~ {week_end}（周日）")

    # 加载数据
    df_all, dates = load_week_data(week_start, week_end)
    if df_all is None:
        print("[ERROR] 上周无任何 CSV 数据")
        sys.exit(1)
    print(f"[INFO] 加载 {len(df_all)} 条原始记录, 覆盖 {len(dates)} 天: {', '.join(dates)}")

    df_calc = df_all[df_all['NOTE'] == '正常'].copy()
    print(f"[INFO] 正常生产 {len(df_calc)} 条, {df_calc['LINE_ID'].nunique()} 条产线")

    if len(df_calc) == 0:
        print("[ERROR] 上周无正常生产记录")
        sys.exit(1)

    # 生成图表
    print("[INFO] 生成图表...")
    fig_dept, dept_data = chart_weekly_dept(df_calc)
    charts = {
        'weekly_dept': fig_to_base64(fig_dept),
        'daily_trend': fig_to_base64(chart_daily_trend(df_calc, dates)),
    }

    # 生成 HTML
    print("[INFO] 生成 HTML...")
    html = generate_weekly_html(df_all, df_calc, charts, dept_data, week_start, week_end, dates)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"生产周报_{week_start.strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[OK] {output_file} ({output_file.stat().st_size/1024:.0f} KB)")

    sp = int(df_calc['PLANQTY'].sum())
    sa = int(df_calc['AUTOQTY'].sum())
    print(f"\n===== 周报摘要 =====\n周期: {week_start} ~ {week_end} ({len(dates)}天)\n周计划: {sp:,} | 周产出: {sa:,} | 达成率: {(sa/sp*100) if sp>0 else 0:.1f}%\n====================")


if __name__ == '__main__':
    main()

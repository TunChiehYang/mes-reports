#!/usr/bin/env python3
"""
生产计划 vs 实际产出 日报分析脚本
读取 D:\ShareExport\output\V_PLAN_ACTUAL_SUMMARY 下当天最新 CSV，
生成含可视化图表的 HTML 报告，输出到 D:\outputHTML\
"""

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import os
import sys
import base64
import io
from datetime import datetime, date, timedelta
from pathlib import Path
import glob

# ============ 配置 ============
SOURCE_DIR = Path("/mnt/d/ShareExport/output/V_PLAN_ACTUAL_SUMMARY")
OUTPUT_DIR = Path("/mnt/d/outputHTML")
ENCODING = "gbk"

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

# ============ 工具函数 ============

def parse_ach(val):
    """解析达成率字符串为数值"""
    if pd.isna(val):
        return 0.0
    s = str(val).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def find_latest_csv(target_date=None):
    """找到指定日期最新的 CSV 文件，默认今天"""
    if target_date is None:
        target_date = date.today()
    date_str = target_date.strftime("%Y%m%d")
    pattern = f"V_PLAN_ACTUAL_SUMMARY_{date_str}_*.csv"
    files = sorted(SOURCE_DIR.glob(pattern), reverse=True)
    if not files:
        # 尝试前一天
        yesterday = target_date - timedelta(days=1)
        date_str_y = yesterday.strftime("%Y%m%d")
        pattern_y = f"V_PLAN_ACTUAL_SUMMARY_{date_str_y}_*.csv"
        files = sorted(SOURCE_DIR.glob(pattern_y), reverse=True)
        if not files:
            print(f"[WARN] 未找到 {target_date} 或前一天的 CSV 文件，尝试最新文件...")
            files = sorted(SOURCE_DIR.glob("V_PLAN_ACTUAL_SUMMARY_*.csv"), reverse=True)
    return files[0] if files else None


def load_data(filepath):
    """加载并清洗 CSV 数据"""
    df = pd.read_csv(filepath, encoding=ENCODING)
    # 解析达成率数值
    df['ACH_NUM'] = df['ACH'].apply(parse_ach)
    # 填充空值
    df['ACTUAL_WO_LIST'] = df['ACTUAL_WO_LIST'].fillna('')
    df['ACTUAL_MODEL_LIST'] = df['ACTUAL_MODEL_LIST'].fillna('')
    df['NOTE'] = df['NOTE'].fillna('未知')
    df['CLAS_TYPE'] = df['CLAS_TYPE'].fillna('未知')
    return df


def fig_to_base64(fig):
    """将 matplotlib figure 转为 base64 字符串"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64


# ============ 图表生成 ============

def chart_ach_by_line(df, title, max_items=30):
    """各产线达成率柱状图（按传入的 df 范围）"""
    # 按产线汇总
    line_summary = df.groupby('LINE_ID').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum')
    ).reset_index()
    line_summary['ACH'] = (line_summary['AUTOQTY'] / line_summary['PLANQTY'].replace(0, np.nan) * 100).fillna(0)
    line_summary = line_summary[line_summary['PLANQTY'] > 0]
    # 按达成率排序
    line_summary = line_summary.sort_values('ACH', ascending=True).tail(max_items)

    if len(line_summary) == 0:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.text(0.5, 0.5, '无数据', ha='center', va='center', fontsize=16, color='#95a5a6', transform=ax.transAxes)
        ax.set_title(title, fontsize=14, fontweight='bold')
        return fig

    fig, ax = plt.subplots(figsize=(12, max(6, len(line_summary) * 0.28)))
    colors = ['#e74c3c' if v < 50 else '#f39c12' if v < 80 else '#27ae60' for v in line_summary['ACH']]
    bars = ax.barh(range(len(line_summary)), line_summary['ACH'], color=colors, edgecolor='white', height=0.7)

    # 标注数值
    for i, (ach, plan, actual) in enumerate(zip(line_summary['ACH'],
                                                  line_summary['PLANQTY'],
                                                  line_summary['AUTOQTY'])):
        ax.text(ach + 0.5, i, f'{ach:.1f}% ({int(actual)}/{int(plan)})',
                va='center', fontsize=7, color='#333')

    ax.set_yticks(range(len(line_summary)))
    ax.set_yticklabels(line_summary['LINE_ID'], fontsize=8)
    ax.set_xlabel('达成率 (%)', fontsize=11)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlim(0, max(line_summary['ACH']) * 1.2 + 5)
    ax.axvline(x=80, color='#e67e22', linestyle='--', alpha=0.6, label='80% 目标线')
    ax.axvline(x=100, color='#2ecc71', linestyle='--', alpha=0.6, label='100% 达标线')
    ax.legend(fontsize=9, loc='lower right')
    ax.grid(axis='x', alpha=0.3)
    fig.tight_layout()
    return fig


def chart_shift_comparison(df):
    """白班 vs 夜班对比"""
    shift = df[df['CLAS_TYPE'].isin(['白班', '夜班'])].groupby('CLAS_TYPE').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        LINES=('LINE_ID', 'nunique')
    ).reset_index()
    shift['ACH'] = (shift['AUTOQTY'] / shift['PLANQTY'].replace(0, np.nan) * 100).fillna(0)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 左图: 计划 vs 实际
    x = np.arange(len(shift))
    w = 0.35
    ax = axes[0]
    ax.bar(x - w/2, shift['PLANQTY'] / 1000, w, label='计划量', color='#3498db', edgecolor='white')
    ax.bar(x + w/2, shift['AUTOQTY'] / 1000, w, label='实际产出', color='#e74c3c', edgecolor='white')
    for i, (p, a) in enumerate(zip(shift['PLANQTY'], shift['AUTOQTY'])):
        ax.text(i - w/2, p/1000 + 5, str(int(p)), ha='center', fontsize=9)
        ax.text(i + w/2, a/1000 + 5, str(int(a)), ha='center', fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(shift['CLAS_TYPE'], fontsize=11)
    ax.set_ylabel('数量 (千)', fontsize=11)
    ax.set_title('白班 vs 夜班 计划/实际对比', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)

    # 右图: 达成率
    ax = axes[1]
    colors = ['#f39c12', '#2c3e50']
    bars = ax.bar(shift['CLAS_TYPE'], shift['ACH'], color=colors, edgecolor='white', width=0.4)
    for bar, ach in zip(bars, shift['ACH']):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{ach:.1f}%', ha='center', fontsize=12, fontweight='bold')
    ax.set_ylabel('达成率 (%)', fontsize=11)
    ax.set_title('白班 vs 夜班 达成率', fontsize=13, fontweight='bold')
    ax.axhline(y=80, color='#27ae60', linestyle='--', alpha=0.6, label='80% 目标线')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    return fig


def chart_status_pie(df):
    """生产状态分布饼图"""
    status = df['NOTE'].value_counts()
    fig, ax = plt.subplots(figsize=(7, 7))
    colors = {'正常': '#27ae60', '无生产': '#e74c3c', '无计划': '#95a5a6', '不正常': '#e67e22', '未知': '#bdc3c7'}
    pie_colors = [colors.get(k, '#bdc3c7') for k in status.index]
    wedges, texts, autotexts = ax.pie(
        status.values, labels=status.index, autopct='%1.1f%%',
        colors=pie_colors, startangle=90,
        textprops={'fontsize': 11}
    )
    for at in autotexts:
        at.set_fontweight('bold')
        at.set_fontsize(10)
    ax.set_title('生产状态分布', fontsize=14, fontweight='bold')
    return fig


def chart_category_summary(df):
    """按产线类别汇总 (NA/NB/NQ)"""
    df_cat = df.copy()
    df_cat['CATEGORY'] = df_cat['LINE_ID'].str.extract(r'^([A-Z]+)')[0]
    cat_summary = df_cat.groupby('CATEGORY').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        LINES=('LINE_ID', 'nunique')
    ).reset_index()
    cat_summary['ACH'] = (cat_summary['AUTOQTY'] / cat_summary['PLANQTY'].replace(0, np.nan) * 100).fillna(0)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    ax = axes[0]
    x = np.arange(len(cat_summary))
    w = 0.35
    ax.bar(x - w/2, cat_summary['PLANQTY'] / 1000, w, label='计划量', color='#3498db', edgecolor='white')
    ax.bar(x + w/2, cat_summary['AUTOQTY'] / 1000, w, label='实际产出', color='#e74c3c', edgecolor='white')
    ax.set_xticks(x)
    ax.set_xticklabels(cat_summary['CATEGORY'], fontsize=11)
    ax.set_ylabel('数量 (千)', fontsize=11)
    ax.set_title('产线类别 计划/实际对比', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)

    ax = axes[1]
    bars = ax.bar(cat_summary['CATEGORY'], cat_summary['ACH'], color=['#3498db', '#e67e22', '#2ecc71'], edgecolor='white', width=0.4)
    for bar, ach in zip(bars, cat_summary['ACH']):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{ach:.1f}%', ha='center', fontsize=11, fontweight='bold')
    ax.set_ylabel('达成率 (%)', fontsize=11)
    ax.set_title('产线类别 达成率', fontsize=13, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    return fig


# ============ HTML 生成 ============

def get_dept(line_id):
    """根据产线ID返回所属部门"""
    cat = ''.join(c for c in str(line_id) if c.isalpha())
    num_str = ''.join(c for c in str(line_id) if c.isdigit())
    num = int(num_str) if num_str else 0

    if cat == 'NA':
        if 1 <= num <= 9:
            return '冲压一课'
        if num in (19, 20, 21):
            return '冲压一课'
        if 10 <= num <= 18:
            return '冲压二课'
        if 23 <= num <= 32:
            return '冲压三课'
    if cat == 'NB':
        if 1 <= num <= 5:
            return '冲压一课'
        if num == 26:
            return '冲压一课'
        if 6 <= num <= 10:
            return '冲压二课'
        if 11 <= num <= 25:
            return '冲压三课'
    if cat == 'NQ':
        if 101 <= num <= 115:
            return '清洗一课'
        if 301 <= num <= 310:
            return '清洗一课'
        if 201 <= num <= 224:
            return '清洗二课'
        if 401 <= num <= 412:
            return '清洗三课'
        if 501 <= num <= 512:
            return '清洗三课'
    return '其他'

def get_parent_dept(dept_name):
    """返回部门的上级（制造一部/制造二部）"""
    if dept_name.startswith('冲压'):
        return '制造一部'
    if dept_name.startswith('清洗'):
        return '制造二部'
    return '其他'


def chart_dept_summary(df):
    """部门达成率对比图（冲压一课/二课/三课/组装线）"""
    df_d = df.copy()
    df_d['DEPT'] = df_d['LINE_ID'].apply(get_dept)
    dept = df_d.groupby('DEPT').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        LINES=('LINE_ID', 'nunique')
    ).reset_index()
    dept['ACH'] = (dept['AUTOQTY'] / dept['PLANQTY'].replace(0, np.nan) * 100).fillna(0)
    # 固定顺序
    order = {'冲压一课': 0, '冲压二课': 1, '冲压三课': 2,
             '清洗一课': 3, '清洗二课': 4, '清洗三课': 5}
    dept['SORT'] = dept['DEPT'].map(order)
    dept = dept.dropna(subset=['SORT']).sort_values('SORT')

    fig, axes = plt.subplots(1, 2, figsize=(16, 5.5))

    x = np.arange(len(dept))
    w = 0.35
    ax = axes[0]
    ax.bar(x - w/2, dept['PLANQTY'] / 1000, w, label='计划量', color='#3498db', edgecolor='white')
    ax.bar(x + w/2, dept['AUTOQTY'] / 1000, w, label='实际产出', color='#e74c3c', edgecolor='white')
    for i, (p, a) in enumerate(zip(dept['PLANQTY'], dept['AUTOQTY'])):
        ax.text(i - w/2, p/1000 + 1, f'{int(p):,}', ha='center', fontsize=7)
        ax.text(i + w/2, a/1000 + 1, f'{int(a):,}', ha='center', fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(dept['DEPT'], fontsize=9)
    ax.set_ylabel('数量 (千)', fontsize=11)
    ax.set_title('各部门 计划/实际对比', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    # 添加制造一部/二部分隔线
    if len(dept) >= 4:
        ax.axvline(x=2.5, color='#2c3e50', linestyle='-', alpha=0.3, linewidth=2)
        ax.text(1.0, ax.get_ylim()[1]*0.97, '制造一部', ha='center', fontsize=9,
                color='#2c3e50', fontweight='bold')
        ax.text(4.0, ax.get_ylim()[1]*0.97, '制造二部', ha='center', fontsize=9,
                color='#2c3e50', fontweight='bold')

    ax = axes[1]
    colors = ['#3498db', '#e67e22', '#9b59b6', '#1abc9c', '#2ecc71', '#e74c3c']
    bars = ax.bar(dept['DEPT'], dept['ACH'], color=colors[:len(dept)], edgecolor='white', width=0.5)
    for bar, ach in zip(bars, dept['ACH']):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f'{ach:.1f}%', ha='center', fontsize=11, fontweight='bold')
    ax.set_ylabel('达成率 (%)', fontsize=11)
    ax.set_title('各部门 达成率对比', fontsize=13, fontweight='bold')
    ax.axhline(y=80, color='#27ae60', linestyle='--', alpha=0.6, label='80% 目标线')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    return fig, dept


def generate_html(df, charts, report_date, source_file, shift_label="白班"):
    """生成 HTML 报告"""
    # 统计数据：仅统计"正常"行
    df_calc = df[df['NOTE'] == '正常'].copy()

    # 基础统计（仅正常生产）
    total_plan = int(df_calc['PLANQTY'].sum())
    total_actual = int(df_calc['AUTOQTY'].sum())
    overall_ach = (total_actual / total_plan * 100) if total_plan > 0 else 0

    # 达成率（正常生产的达成率即整体达成率）
    normal_ach = overall_ach

    # 达成率最高/最低产线（按类别分开，基于 df_calc）
    line_ach = df_calc.groupby('LINE_ID').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        MODEL=('ACTUAL_MODEL_LIST', lambda x: ' / '.join(sorted(set([m for m in x if m and str(m).strip()]))))
    ).reset_index()
    line_ach['ACH'] = (line_ach['AUTOQTY'] / line_ach['PLANQTY'].replace(0, np.nan) * 100).fillna(0)
    line_ach = line_ach[line_ach['PLANQTY'] > 0].sort_values('ACH', ascending=False)
    line_ach['CAT'] = line_ach['LINE_ID'].str.extract(r'^([A-Z]+)')[0]

    # 冲压线 (NA/NB)
    stamping = line_ach[line_ach['CAT'].isin(['NA', 'NB'])].sort_values('ACH', ascending=False)
    stamping_top5 = stamping.head(10)
    stamping_bottom5 = stamping.tail(10)

    # 组装线 (NQ)
    assembly = line_ach[line_ach['CAT'].isin(['NQ'])].sort_values('ACH', ascending=False)
    assembly_top5 = assembly.head(10)
    assembly_bottom5 = assembly.tail(10)

    # 冲压线统计
    stamping_plan = int(stamping['PLANQTY'].sum()) if len(stamping) > 0 else 0
    stamping_actual = int(stamping['AUTOQTY'].sum()) if len(stamping) > 0 else 0
    stamping_ach = (stamping_actual / stamping_plan * 100) if stamping_plan > 0 else 0
    # 组装线统计
    assembly_plan = int(assembly['PLANQTY'].sum()) if len(assembly) > 0 else 0
    assembly_actual = int(assembly['AUTOQTY'].sum()) if len(assembly) > 0 else 0
    assembly_ach = (assembly_actual / assembly_plan * 100) if assembly_plan > 0 else 0

    # 制造一部/二部 × 白班/夜班 交叉统计
    df_calc['IS_DEPT1'] = df_calc['LINE_ID'].str.match(r'^(NA|NB)')
    shifts_data = {}
    for dept_key, dept_label in [(True, '制造一部'), (False, '制造二部')]:
        for shift in ['白班', '夜班']:
            sub = df_calc[(df_calc['IS_DEPT1'] == dept_key) & (df_calc['CLAS_TYPE'] == shift)]
            p = int(sub['PLANQTY'].sum())
            a = int(sub['AUTOQTY'].sum())
            ach = a / p * 100 if p else 0
            lines = sub['LINE_ID'].nunique()
            shifts_data[(dept_label, shift)] = {'plan': p, 'actual': a, 'ach': ach, 'lines': lines}

    # 部门统计（冲压一课/二课/三课/组装线）
    line_ach['DEPT'] = line_ach['LINE_ID'].apply(get_dept)
    dept_summary = line_ach.groupby('DEPT').agg(
        PLANQTY=('PLANQTY', 'sum'),
        AUTOQTY=('AUTOQTY', 'sum'),
        LINES=('LINE_ID', 'nunique')
    ).reset_index()
    dept_summary['ACH'] = (dept_summary['AUTOQTY'] / dept_summary['PLANQTY'].replace(0, np.nan) * 100).fillna(0)
    dept_order = {'冲压一课': 0, '冲压二课': 1, '冲压三课': 2,
                  '清洗一课': 3, '清洗二课': 4, '清洗三课': 5}
    dept_summary['SORT'] = dept_summary['DEPT'].map(dept_order)
    dept_summary = dept_summary.dropna(subset=['SORT']).sort_values('SORT')

    # 各部门 Top/Bottom
    ALL_DEPTS = ['冲压一课', '冲压二课', '冲压三课', '清洗一课', '清洗二课', '清洗三课']
    dept_tables = {}
    for dept_name in ALL_DEPTS:
        d_lines = line_ach[line_ach['DEPT'] == dept_name].sort_values('ACH', ascending=False)
        dept_tables[dept_name] = {
            'top': d_lines.head(3),
            'bottom': d_lines.tail(3),
            'count': len(d_lines),
            'plan': int(d_lines['PLANQTY'].sum()) if len(d_lines) > 0 else 0,
            'actual': int(d_lines['AUTOQTY'].sum()) if len(d_lines) > 0 else 0,
            'ach': (d_lines['AUTOQTY'].sum() / d_lines['PLANQTY'].sum() * 100) if len(d_lines) > 0 and d_lines['PLANQTY'].sum() > 0 else 0,
        }

    # 制造一部/制造二部汇总
    dept1_plan = sum(int(r['PLANQTY']) for _, r in dept_summary.iterrows() if r['DEPT'] in ['冲压一课','冲压二课','冲压三课'])
    dept1_auto = sum(int(r['AUTOQTY']) for _, r in dept_summary.iterrows() if r['DEPT'] in ['冲压一课','冲压二课','冲压三课'])
    dept1_lines = sum(int(r['LINES']) for _, r in dept_summary.iterrows() if r['DEPT'] in ['冲压一课','冲压二课','冲压三课'])
    dept1_ach = dept1_auto / dept1_plan * 100 if dept1_plan else 0
    dept2_plan = sum(int(r['PLANQTY']) for _, r in dept_summary.iterrows() if r['DEPT'] in ['清洗一课','清洗二课','清洗三课'])
    dept2_auto = sum(int(r['AUTOQTY']) for _, r in dept_summary.iterrows() if r['DEPT'] in ['清洗一课','清洗二课','清洗三课'])
    dept2_lines = sum(int(r['LINES']) for _, r in dept_summary.iterrows() if r['DEPT'] in ['清洗一课','清洗二课','清洗三课'])
    dept2_ach = dept2_auto / dept2_plan * 100 if dept2_plan else 0

    # 生成部门统计表行
    dept_rows = ""
    dept1_added = False
    for _, r in dept_summary.iterrows():
        # 在冲压一课前插入制造一部汇总行
        if not dept1_added and r['DEPT'] == '冲压一课':
            d1c = '#27ae60' if dept1_ach >= 80 else '#f39c12' if dept1_ach >= 50 else '#e74c3c'
            dept_rows += f"""<tr style="background:#f0f4f8;font-weight:700">
                <td>制造一部</td><td>{dept1_lines}</td><td>{dept1_plan:,}</td>
                <td>{dept1_auto:,}</td><td style="color:{d1c}">{dept1_ach:.1f}%</td>
            </tr>"""
            dept1_added = True
        # 在清洗一课前插入制造二部汇总行
        if r['DEPT'] == '清洗一课':
            d2c = '#27ae60' if dept2_ach >= 80 else '#f39c12' if dept2_ach >= 50 else '#e74c3c'
            dept_rows += f"""<tr style="background:#f0f4f8;font-weight:700">
                <td>制造二部</td><td>{dept2_lines}</td><td>{dept2_plan:,}</td>
                <td>{dept2_auto:,}</td><td style="color:{d2c}">{dept2_ach:.1f}%</td>
            </tr>"""
        ach_c = '#27ae60' if r['ACH'] >= 80 else '#f39c12' if r['ACH'] >= 50 else '#e74c3c'
        dept_rows += f"""<tr>
            <td style="font-weight:bold">{r['DEPT']}</td>
            <td>{int(r['LINES'])}</td>
            <td>{int(r['PLANQTY']):,}</td>
            <td>{int(r['AUTOQTY']):,}</td>
            <td style="color:{ach_c};font-weight:bold">{r['ACH']:.1f}%</td>
        </tr>"""

    # 各部门 Top/Bottom 表 HTML（按制造一部/二部分组）
    dept_table_html = ""
    dept_colors = {'冲压一课': '#3498db', '冲压二课': '#e67e22', '冲压三课': '#9b59b6',
                   '清洗一课': '#1abc9c', '清洗二课': '#2ecc71', '清洗三课': '#e74c3c'}
    current_parent = None
    for dept_name in ALL_DEPTS:
        parent = get_parent_dept(dept_name)
        if parent != current_parent:
            current_parent = parent
            dept_table_html += f"""
    <h2 style="color:#2c3e50;margin:32px 0 16px 0;padding:12px 20px;background:linear-gradient(135deg, #ecf0f1, #dfe6e9);border-radius:8px;font-size:18px;">🏭 {parent}</h2>"""
        d = dept_tables[dept_name]
        color = dept_colors[dept_name]
        top_rows = ''.join(f'''<tr>
            <td>{r['LINE_ID']}</td>
            <td style="font-size:12px;color:#555">{str(r.get('MODEL','')).strip() or '-'}</td>
            <td>{int(r['PLANQTY']):,}</td>
            <td>{int(r['AUTOQTY']):,}</td>
            <td style="color:#27ae60;font-weight:bold">{r['ACH']:.1f}%</td>
        </tr>''' for _, r in d['top'].iterrows()) if len(d['top']) > 0 else '<tr><td colspan="5" style="color:#95a5a6">无数据</td></tr>'
        bottom_rows = ''.join(f'''<tr>
            <td>{r['LINE_ID']}</td>
            <td style="font-size:12px;color:#555">{str(r.get('MODEL','')).strip() or '-'}</td>
            <td>{int(r['PLANQTY']):,}</td>
            <td>{int(r['AUTOQTY']):,}</td>
            <td style="color:#e74c3c;font-weight:bold">{r['ACH']:.1f}%</td>
        </tr>''' for _, r in d['bottom'].iterrows()) if len(d['bottom']) > 0 else '<tr><td colspan="5" style="color:#95a5a6">无数据</td></tr>'

        dept_table_html += f"""
    <h3 style="color:#2c3e50;margin:24px 0 12px 0;padding-bottom:6px;border-bottom:2px solid {color};">{dept_name} ({d['count']}条产线 | 计划{int(d['plan']):,} | 实际{int(d['actual']):,} | 达成率 {d['ach']:.1f}%)</h3>
    <div class="two-col">
        <div class="table-section">
            <h3 style="margin-bottom:10px;color:#27ae60">🏆 Top 3</h3>
            <table>
                <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
                {top_rows}
            </table>
        </div>
        <div class="table-section">
            <h3 style="margin-bottom:10px;color:#e74c3c">⚠️ Bottom 3</h3>
            <table>
                <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
                {bottom_rows}
            </table>
        </div>
    </div>"""

    # 生成产线详情表
    detail_rows = ""
    for _, row in line_ach.iterrows():
        ach_color = '#27ae60' if row['ACH'] >= 80 else '#f39c12' if row['ACH'] >= 50 else '#e74c3c'
        model = str(row.get('MODEL', '')).strip() or '-'
        detail_rows += f"""<tr>
            <td>{row['LINE_ID']}</td>
            <td style="font-size:12px;color:#555">{model}</td>
            <td>{int(row['PLANQTY']):,}</td>
            <td>{int(row['AUTOQTY']):,}</td>
            <td style="color:{ach_color};font-weight:bold">{row['ACH']:.1f}%</td>
        </tr>"""

    # 状态统计表
    status_counts = df['NOTE'].value_counts()
    status_rows = ""
    for status, count in status_counts.items():
        color_map = {'正常': '#27ae60', '无生产': '#e74c3c', '无计划': '#95a5a6', '不正常': '#e67e22'}
        color = color_map.get(status, '#333')
        status_rows += f"""<tr>
            <td style="color:{color};font-weight:bold">{status}</td>
            <td>{count}</td>
            <td>{count/len(df)*100:.1f}%</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>生产日报 - {report_date} {shift_label}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, 'Microsoft YaHei', sans-serif;
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        min-height: 100vh;
        padding: 20px;
        -webkit-user-select: text;
        user-select: text;
    }}
    .container {{ max-width: 1300px; margin: 0 auto; }}
    .header {{
        background: linear-gradient(135deg, #2c3e50 0%, #3498db 100%);
        color: white;
        padding: 30px 40px;
        border-radius: 16px;
        margin-bottom: 24px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.15);
    }}
    .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
    .header .meta {{ font-size: 14px; opacity: 0.85; }}
    .kpi-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
    }}
    .kpi-card {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        text-align: center;
    }}
    .kpi-card .kpi-label {{ font-size: 13px; color: #7f8c8d; margin-bottom: 6px; }}
    .kpi-card .kpi-value {{ font-size: 32px; font-weight: bold; margin-bottom: 4px; }}
    .kpi-card .kpi-sub {{ font-size: 12px; color: #95a5a6; }}
    .chart-section {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
        margin-bottom: 24px;
    }}
    .chart-card {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.08);
    }}
    .chart-card.full-width {{ grid-column: 1 / -1; }}
    .chart-card img {{ width: 100%; height: auto; border-radius: 8px; }}
    .chart-card h3 {{
        font-size: 16px;
        color: #2c3e50;
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 2px solid #ecf0f1;
    }}
    .table-section {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        margin-bottom: 24px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
    }}
    th {{
        background: #2c3e50;
        color: white;
        padding: 12px 16px;
        text-align: left;
        font-size: 13px;
    }}
    td {{
        padding: 10px 16px;
        border-bottom: 1px solid #ecf0f1;
        font-size: 13px;
    }}
    tr:hover {{ background: #f8f9fa; }}
    .highlight-box {{
        background: linear-gradient(135deg, #fff9e6, #ffeaa7);
        border-left: 4px solid #f39c12;
        padding: 16px 20px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 20px;
        font-size: 14px;
        line-height: 1.8;
    }}
    .highlight-box strong {{ color: #e67e22; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    .footer {{
        text-align: center;
        color: #95a5a6;
        font-size: 12px;
        padding: 20px;
    }}
    @media (max-width: 900px) {{
        .chart-section {{ grid-template-columns: 1fr; }}
        .two-col {{ grid-template-columns: 1fr; }}
    }}
</style>
<script>
// 确保 Ctrl+C 复制不受外层页面拦截
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

    <!-- 头部 -->
    <div class="header">
        <h1>📊 生产日报 — {shift_label}报表</h1>
        <div class="meta">
            报告日期：{report_date} &nbsp;|&nbsp;
            班次：<strong>{shift_label}</strong> &nbsp;|&nbsp;
            数据来源：{source_file.name} &nbsp;|&nbsp;
            生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>

    <!-- 关键指标卡片：制造一部/二部 × 白班/夜班 -->
    <div style="margin-bottom:18px">
        <h3 style="color:#2c3e50;margin-bottom:10px;padding:8px 14px;background:#eaf2f8;border-radius:8px;font-size:16px">🏭 制造一部（冲压）</h3>
        <div class="kpi-grid">
            <div class="kpi-card" style="border-left:4px solid #3498db">
                <div class="kpi-label">🌙 夜班</div>
                <div class="kpi-value" style="color:#3498db;font-size:22px">{shifts_data[('制造一部','夜班')]['plan']:,}</div>
                <div class="kpi-sub">计划 / 实际 {shifts_data[('制造一部','夜班')]['actual']:,} / 达成率 {shifts_data[('制造一部','夜班')]['ach']:.1f}% / {shifts_data[('制造一部','夜班')]['lines']}线</div>
            </div>
            <div class="kpi-card" style="border-left:4px solid #f39c12">
                <div class="kpi-label">☀️ 白班</div>
                <div class="kpi-value" style="color:#f39c12;font-size:22px">{shifts_data[('制造一部','白班')]['plan']:,}</div>
                <div class="kpi-sub">计划 / 实际 {shifts_data[('制造一部','白班')]['actual']:,} / 达成率 {shifts_data[('制造一部','白班')]['ach']:.1f}% / {shifts_data[('制造一部','白班')]['lines']}线</div>
            </div>
        </div>
    </div>
    <div style="margin-bottom:18px">
        <h3 style="color:#2c3e50;margin-bottom:10px;padding:8px 14px;background:#e8f8f5;border-radius:8px;font-size:16px">🏗️ 制造二部（清洗）</h3>
        <div class="kpi-grid">
            <div class="kpi-card" style="border-left:4px solid #2980b9">
                <div class="kpi-label">🌙 夜班</div>
                <div class="kpi-value" style="color:#2980b9;font-size:22px">{shifts_data[('制造二部','夜班')]['plan']:,}</div>
                <div class="kpi-sub">计划 / 实际 {shifts_data[('制造二部','夜班')]['actual']:,} / 达成率 {shifts_data[('制造二部','夜班')]['ach']:.1f}% / {shifts_data[('制造二部','夜班')]['lines']}线</div>
            </div>
            <div class="kpi-card" style="border-left:4px solid #e67e22">
                <div class="kpi-label">☀️ 白班</div>
                <div class="kpi-value" style="color:#e67e22;font-size:22px">{shifts_data[('制造二部','白班')]['plan']:,}</div>
                <div class="kpi-sub">计划 / 实际 {shifts_data[('制造二部','白班')]['actual']:,} / 达成率 {shifts_data[('制造二部','白班')]['ach']:.1f}% / {shifts_data[('制造二部','白班')]['lines']}线</div>
            </div>
        </div>
    </div>
    <div class="kpi-grid" style="margin-bottom:16px">
        <div class="kpi-card" style="background:#f8f9fa">
            <div class="kpi-label">📊 全厂合计</div>
            <div class="kpi-value" style="color:#2c3e50;font-size:20px">{total_plan:,} / {total_actual:,}</div>
            <div class="kpi-sub">计划/实际 | 达成率 {overall_ach:.1f}% | {df_calc['LINE_ID'].nunique()}条线</div>
        </div>
    </div>

    <!-- 摘要 -->
    <div class="highlight-box">
        <strong>📝 摘要：</strong>
        本日正常生产涉及 <strong>{df_calc['LINE_ID'].nunique()}</strong> 条产线，计划总产量 <strong>{total_plan:,}</strong> 件，实际产出 <strong>{total_actual:,}</strong> 件，达成率 <strong>{overall_ach:.1f}%</strong>
        （原始数据共 {len(df)} 条记录，其中正常 {len(df_calc)} 条）。<br>
        {''.join(f'<strong>{r["DEPT"]}</strong>：{int(r["LINES"])}条产线，计划{int(r["PLANQTY"]):,}件，实际{int(r["AUTOQTY"]):,}件，达成率<strong>{r["ACH"]:.1f}%</strong>；<br>' for _, r in dept_summary.iterrows())}
    </div>

    <!-- 图表区 第一行 -->
    <div class="chart-section">
        <div class="chart-card">
            <h3>🏭 制造一部 达成率排名 (NA/NB)</h3>
            <img src="data:image/png;base64,{charts['ach_stamping']}" alt="冲压线达成率">
        </div>
        <div class="chart-card">
            <h3>🏗️ 制造二部 达成率排名 (NQ)</h3>
            <img src="data:image/png;base64,{charts['ach_assembly']}" alt="组装线达成率">
        </div>
    </div>

    <!-- 图表区 第二行 -->
    <div class="chart-section">
        <div class="chart-card">
            <h3>🥧 生产状态分布</h3>
            <img src="data:image/png;base64,{charts['status_pie']}" alt="状态分布">
        </div>
        <div class="chart-card">
            <h3>🌗 白班 vs 夜班 对比分析</h3>
            <img src="data:image/png;base64,{charts['shift_comparison']}" alt="班次对比">
        </div>
    </div>

    <!-- 图表区 第三行 -->
    <div class="chart-section">
        <div class="chart-card full-width">
            <h3>🏢 各部门达成率对比（冲压 / 清洗 共 6 课）</h3>
            <img src="data:image/png;base64,{charts['dept_summary']}" alt="部门对比">
        </div>
    </div>

    <!-- 部门汇总表 -->
    <div class="table-section">
        <h3 style="margin-bottom:12px;color:#2c3e50">🏢 部门达成率汇总</h3>
        <table>
            <tr><th>部门</th><th>产线数</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
            {dept_rows}
        </table>
    </div>

    {dept_table_html}

    <!-- 达成率排名表：冲压线（整体） -->
    <h3 style="color:#2c3e50;margin:24px 0 16px 0;padding-bottom:8px;border-bottom:2px solid #3498db;">🔧 制造一部（冲压）达成率排名</h3>
    <div class="two-col">
        <div class="table-section">
            <h3 style="margin-bottom:12px;color:#27ae60">🏆 制造一部 Top 10</h3>
            <table>
                <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
                {''.join(f'''<tr>
                    <td>{r['LINE_ID']}</td>
                    <td style="font-size:12px;color:#555">{str(r.get('MODEL','')).strip() or '-'}</td>
                    <td>{int(r['PLANQTY']):,}</td>
                    <td>{int(r['AUTOQTY']):,}</td>
                    <td style="color:#27ae60;font-weight:bold">{r['ACH']:.1f}%</td>
                </tr>''' for _, r in stamping_top5.iterrows()) if len(stamping_top5) > 0 else '<tr><td colspan="5" style="color:#95a5a6">无数据</td></tr>'}
            </table>
        </div>
        <div class="table-section">
            <h3 style="margin-bottom:12px;color:#e74c3c">⚠️ 制造一部 Bottom 10</h3>
            <table>
                <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
                {''.join(f'''<tr>
                    <td>{r['LINE_ID']}</td>
                    <td style="font-size:12px;color:#555">{str(r.get('MODEL','')).strip() or '-'}</td>
                    <td>{int(r['PLANQTY']):,}</td>
                    <td>{int(r['AUTOQTY']):,}</td>
                    <td style="color:#e74c3c;font-weight:bold">{r['ACH']:.1f}%</td>
                </tr>''' for _, r in stamping_bottom5.iterrows()) if len(stamping_bottom5) > 0 else '<tr><td colspan="5" style="color:#95a5a6">无数据</td></tr>'}
            </table>
        </div>
    </div>

    <!-- 达成率排名表：组装线 -->
    <h3 style="color:#2c3e50;margin:24px 0 16px 0;padding-bottom:8px;border-bottom:2px solid #e67e22;">🏗️ 制造二部（清洗）达成率排名</h3>
    <div class="two-col">
        <div class="table-section">
            <h3 style="margin-bottom:12px;color:#27ae60">🏆 制造二部 Top 10</h3>
            <table>
                <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
                {''.join(f'''<tr>
                    <td>{r['LINE_ID']}</td>
                    <td style="font-size:12px;color:#555">{str(r.get('MODEL','')).strip() or '-'}</td>
                    <td>{int(r['PLANQTY']):,}</td>
                    <td>{int(r['AUTOQTY']):,}</td>
                    <td style="color:#27ae60;font-weight:bold">{r['ACH']:.1f}%</td>
                </tr>''' for _, r in assembly_top5.iterrows()) if len(assembly_top5) > 0 else '<tr><td colspan="5" style="color:#95a5a6">无数据</td></tr>'}
            </table>
        </div>
        <div class="table-section">
            <h3 style="margin-bottom:12px;color:#e74c3c">⚠️ 制造二部 Bottom 10</h3>
            <table>
                <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
                {''.join(f'''<tr>
                    <td>{r['LINE_ID']}</td>
                    <td style="font-size:12px;color:#555">{str(r.get('MODEL','')).strip() or '-'}</td>
                    <td>{int(r['PLANQTY']):,}</td>
                    <td>{int(r['AUTOQTY']):,}</td>
                    <td style="color:#e74c3c;font-weight:bold">{r['ACH']:.1f}%</td>
                </tr>''' for _, r in assembly_bottom5.iterrows()) if len(assembly_bottom5) > 0 else '<tr><td colspan="5" style="color:#95a5a6">无数据</td></tr>'}
            </table>
        </div>
    </div>

    <!-- 生产状态统计 -->
    <div class="table-section">
        <h3 style="margin-bottom:12px;color:#2c3e50">📋 生产状态统计</h3>
        <table>
            <tr><th>状态</th><th>记录数</th><th>占比</th></tr>
            {status_rows}
        </table>
    </div>

    <!-- 全部产线明细 -->
    <div class="table-section">
        <h3 style="margin-bottom:12px;color:#2c3e50">📋 全部产线达成明细</h3>
        <table>
            <tr><th>产线</th><th>机种名</th><th>计划量</th><th>实际产出</th><th>达成率</th></tr>
            {detail_rows}
        </table>
    </div>

    <div class="footer">
        由 Hermes Agent 自动生成 &nbsp;|&nbsp; {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>
</body>
</html>"""
    return html


# ============ 主流程 ============

def main():
    target_date = date.today()
    # 支持命令行参数指定日期
    if len(sys.argv) > 1:
        try:
            target_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        except ValueError:
            print(f"[ERROR] 日期格式错误: {sys.argv[1]}，应为 YYYY-MM-DD")
            sys.exit(1)

    print(f"[INFO] 报告日期: {target_date}")

    # 1. 找文件
    csv_file = find_latest_csv(target_date)
    if csv_file is None:
        print(f"[ERROR] 未找到任何 CSV 文件于 {SOURCE_DIR}")
        sys.exit(1)
    print(f"[INFO] 数据文件: {csv_file}")

    # 2. 加载数据
    df = load_data(csv_file)
    df_calc_main = df[df['NOTE'] == '正常'].copy()
    print(f"[INFO] 加载 {len(df)} 条原始记录, 正常生产 {len(df_calc_main)} 条, "
          f"有效产线 {df_calc_main['LINE_ID'].nunique()} 条")

    # 分类数据（基于 df_calc）
    df_cat = df_calc_main.copy()
    df_cat['CAT'] = df_cat['LINE_ID'].str.extract(r'^([A-Z]+)')[0]
    stamping_main = df_cat[df_cat['CAT'].isin(['NA', 'NB'])]
    assembly_main = df_cat[df_cat['CAT'].isin(['NQ'])]

    # 3. 生成图表
    print("[INFO] 生成图表...")
    charts = {
        'ach_stamping': fig_to_base64(chart_ach_by_line(stamping_main, '冲压线达成率排名 (NA/NB)')),
        'ach_assembly': fig_to_base64(chart_ach_by_line(assembly_main, '组装线达成率排名 (NQ)')),
        'status_pie': fig_to_base64(chart_status_pie(df)),
        'shift_comparison': fig_to_base64(chart_shift_comparison(df_calc_main)),
        'dept_summary': fig_to_base64(chart_dept_summary(df_calc_main)[0]),
    }

    # 4. 生成 HTML
    print("[INFO] 生成 HTML 报告...")
    # 从文件名提取时间用于输出文件名
    data_time = csv_file.stem.split('_')[-1][:4]
    # 根据数据中 CLAS_TYPE 栏位判断班次
    clas_types = df['CLAS_TYPE'].dropna().unique()
    if '白班' in clas_types and '夜班' in clas_types:
        shift_label = "全日"
    elif '白班' in clas_types:
        shift_label = "白班"
    elif '夜班' in clas_types:
        shift_label = "夜班"
    else:
        shift_label = "全日"
    html = generate_html(df, charts, target_date.strftime('%Y-%m-%d'), csv_file, shift_label)

    # 5. 保存（按时间戳命名，不覆盖）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"生产日报_{target_date.strftime('%Y%m%d')}_{data_time}.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    file_size_kb = output_file.stat().st_size / 1024
    print(f"[OK] 报告已保存: {output_file}")
    print(f"[OK] 文件大小: {file_size_kb:.1f} KB")

    # 6. 输出文本摘要（基于 df_calc，仅正常生产）
    total_plan = int(df_calc_main['PLANQTY'].sum())
    total_actual = int(df_calc_main['AUTOQTY'].sum())
    overall_ach = (total_actual / total_plan * 100) if total_plan > 0 else 0
    lines_count = df_calc_main['LINE_ID'].nunique()
    normal_count = len(df_calc_main[df_calc_main['NOTE'] == '正常'])

    sp = int(stamping_main['PLANQTY'].sum()) if len(stamping_main) > 0 else 0
    sa = int(stamping_main['AUTOQTY'].sum()) if len(stamping_main) > 0 else 0
    ap = int(assembly_main['PLANQTY'].sum()) if len(assembly_main) > 0 else 0
    aa = int(assembly_main['AUTOQTY'].sum()) if len(assembly_main) > 0 else 0

    # 部门统计
    ALL_DEPTS_MAIN = ['冲压一课', '冲压二课', '冲压三课', '清洗一课', '清洗二课', '清洗三课']
    dept_stats = {}
    for dept_name in ALL_DEPTS_MAIN:
        d_df = df_calc_main[df_calc_main['LINE_ID'].apply(get_dept) == dept_name]
        if len(d_df) > 0:
            dp = int(d_df['PLANQTY'].sum())
            da = int(d_df['AUTOQTY'].sum())
            dept_stats[dept_name] = (d_df['LINE_ID'].nunique(), dp, da, (da/dp*100) if dp>0 else 0)
        else:
            dept_stats[dept_name] = (0, 0, 0, 0.0)

    dept_lines = ""
    for dept_name in ALL_DEPTS_MAIN:
        dl, dp, da, dach = dept_stats[dept_name]
        dept_lines += f"  {dept_name}: {dl}条 | 计划: {dp:,} | 实际: {da:,} | 达成率: {dach:.1f}%\n"

    print(f"""
===== 生产日报摘要 ({target_date}) [仅正常生产] =====
产线总数: {lines_count}
计划总量: {total_plan:,} 件 | 实际产出: {total_actual:,} 件 | 整体达成率: {overall_ach:.1f}%
正常生产记录: {normal_count} / {len(df_calc_main)}
--- 部门达成率 ---
{dept_lines}--- 冲压整体 ---
  产线: {stamping_main['LINE_ID'].nunique()} 条 | 计划: {sp:,} | 实际: {sa:,} | 达成率: {(sa/sp*100) if sp>0 else 0:.1f}%
--- 组装线 ---
  产线: {assembly_main['LINE_ID'].nunique()} 条 | 计划: {ap:,} | 实际: {aa:,} | 达成率: {(aa/ap*100) if ap>0 else 0:.1f}%
报告文件: {output_file}
==============================""")

    return str(output_file)


if __name__ == '__main__':
    main()
    import subprocess; subprocess.run(['python3', '/home/primayang/.hermes/scripts/gen_index.py'])

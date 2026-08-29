#!/usr/bin/env python3
"""Oracle → PG 同步脚本（GET_VALID_WOW 视图函数）
每小时从 Oracle 10.2.20.111 调用 CHIAMES01.GET_VALID_WOW(当天)
写入 PG 10.2.20.127 mes_plan：
  - plan_actual_hourly   工单级历史流水（每小时追加，永久积累）
  - v_plan_actual_current 当前状态（每小时全量刷新）

用法: python3 sync_oracle_to_pg.py [YYYY-MM-DD]   # 缺省=当天
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from datetime import datetime, timedelta

import oracledb
import psycopg2
import psycopg2.extras

# ============ 配置 ============
ORACLE = dict(user='chiames01', password='mes789@456',
              dsn='10.2.20.111:1521/ORCL')
PG = dict(host='10.2.20.127', port=5432, user='postgres',
          password='Chia@1234', dbname='mes_plan')

# GET_VALID_WOW 返回列顺序（与函数 PIPE ROW 定义一致）
COLS = ['LINE_ID', 'WO_ID', 'TPLAN_START', 'CLAS_TYPE',
        'ACTUAL_QTY', 'WO_PLAN_QTY', 'CAPACIT', 'STANDARD_MANPOWER',
        'REASON', 'PART_NO', 'MODEL_NO', 'PARTNER_CODE', 'PARTNER_NAME',
        'TOTAL_QTY', 'OUTPUT_QTY', 'LINE_ID_STATUS', 'DIRECT_WASH']


def to_int(v):
    try:
        return int(v) if v is not None else 0
    except (ValueError, TypeError):
        return 0


def to_str(v, limit=200):
    if v is None:
        return None
    s = str(v).strip()
    return s[:limit] if limit else s


def main():
    # 目标日期（缺省当天）
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = datetime.now().strftime('%Y-%m-%d')
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 目标日期: {target}")

    # ── 1. 读 Oracle ──
    try:
        conn_o = oracledb.connect(**ORACLE)
        cur_o = conn_o.cursor()
        # 用 SYSDATE 取当天实时生产数据（MES 函数标准用法）
        cur_o.execute("SELECT * FROM TABLE(CHIAMES01.GET_VALID_WOW(SYSDATE))")
        rows = cur_o.fetchall()
        cur_o.close()
        conn_o.close()
    except Exception as e:
        print(f"❌ Oracle 读取失败: {type(e).__name__}: {e}")
        return 1
    print(f"  Oracle 返回: {len(rows)} 行 (SYSDATE={datetime.now().strftime('%Y-%m-%d')})")

    # ── 2. 写 PG ──
    try:
        conn_p = psycopg2.connect(**PG)
        cur_p = conn_p.cursor()
        now = datetime.now()

        # 2a. 写入历史流水（追加）
        insert_sql = f"""
            INSERT INTO plan_actual_hourly
            (line_id, wo_id, tplan_start, clas_type, actual_qty, wo_plan_qty,
             capacit, standard_manpower, reason, part_no, model_no,
             partner_code, partner_name, total_qty, output_qty,
             line_id_status, direct_wash, sync_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        data = []
        for r in rows:
            data.append((
                to_str(r[0], 50), to_str(r[1], 50),
                r[2].date() if r[2] else None, to_str(r[3], 10),
                to_int(r[4]), to_int(r[5]), to_int(r[6]), to_int(r[7]),
                to_str(r[8], 50), to_str(r[9], 100), to_str(r[10], 200),
                to_str(r[11], 50), to_str(r[12], 100),
                to_int(r[13]), to_int(r[14]),
                to_str(r[15], 10), to_str(r[16], 10), now,
            ))
        cur_p.executemany(insert_sql, data)

        # 2b. 刷新当前状态表（全量替换，当班分析用）
        cur_p.execute("DELETE FROM v_plan_actual_current")
        cur_p.executemany(f"""
            INSERT INTO v_plan_actual_current
            (line_id, wo_id, tplan_start, clas_type, actual_qty, wo_plan_qty,
             capacit, standard_manpower, reason, part_no, model_no,
             partner_code, partner_name, total_qty, output_qty,
             line_id_status, direct_wash, sync_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, data)

        # 2c. 写入生产日报专用表（追加历史，完整 17 列）
        cur_p.executemany(f"""
            INSERT INTO plan_daily_detail
            (line_id, wo_id, tplan_start, clas_type, actual_qty, wo_plan_qty,
             capacit, standard_manpower, reason, part_no, model_no,
             partner_code, partner_name, total_qty, output_qty,
             line_id_status, direct_wash, sync_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, data)

        conn_p.commit()
        cur_p.close()
        conn_p.close()
    except Exception as e:
        print(f"❌ PG 写入失败: {type(e).__name__}: {e}")
        return 1

    print(f"  ✅ plan_actual_hourly +{len(data)} | v_plan_actual_current {len(data)} | plan_daily_detail +{len(data)}")
    print(f"  ✅ 同步完成 {now.strftime('%Y-%m-%d %H:%M:%S')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

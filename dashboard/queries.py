"""대시보드용 조회 함수. 각 함수는 뷰/함수에 대한 SELECT 한 개만 실행한다.

KPI 계산은 전부 SQL(뷰) 쪽에서 끝나며, 여기서는 DataFrame 으로 옮기고
Decimal -> float 변환만 한다.
"""
import pandas as pd

OEE_COLS = ["equipment_name", "oee", "availability", "performance", "quality"]
WO_COLS = ["wo_id", "item_code", "planned_qty", "good_qty", "progress_pct", "status", "due_date"]
DEFECT_COLS = ["process_code", "input_qty", "defect_qty", "scrap_qty", "rework_qty",
               "defect_rate", "fty"]
EQUIP_COLS = ["equipment_id", "name", "status", "since"]
TRACE_COLS = {
    "forward": ["lot_no", "item_code", "depth"],
    "backward": ["lot_no", "item_code", "supplier_lot_no", "depth"],
}


def _frame(conn, sql, columns, params=None, floats=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=columns)
    for c in floats:
        df[c] = df[c].astype(float)
    return df


def oee_by_equipment(conn) -> pd.DataFrame:
    """설비별 평균 OEE/가용성/성능/품질 (집계는 SQL 에서)."""
    return _frame(
        conn,
        "select equipment_name, avg(oee), avg(availability), avg(performance), avg(quality)"
        " from v_oee_daily group by equipment_name order by equipment_name",
        OEE_COLS, floats=OEE_COLS[1:])


def wo_progress(conn) -> pd.DataFrame:
    return _frame(conn, f"select {', '.join(WO_COLS)} from v_wo_progress order by wo_id",
                  WO_COLS, floats=["progress_pct"])


def defect_by_process(conn) -> pd.DataFrame:
    return _frame(conn, f"select {', '.join(DEFECT_COLS)} from v_defect_rate",
                  DEFECT_COLS, floats=["defect_rate", "fty"])


def equipment_status(conn) -> pd.DataFrame:
    return _frame(conn, f"select {', '.join(EQUIP_COLS)} from v_equipment_current order by equipment_id",
                  EQUIP_COLS)


def lot_trace(conn, lot_no: str, direction: str) -> pd.DataFrame:
    if direction not in TRACE_COLS:
        raise ValueError(f"direction must be 'forward' or 'backward', got {direction!r}")
    cols = TRACE_COLS[direction]
    fn = "trace_forward" if direction == "forward" else "trace_backward"
    return _frame(conn, f"select {', '.join(cols)} from {fn}(%s) order by depth, lot_no",
                  cols, params=(lot_no,))


def kpi_summary(conn) -> dict:
    """상단 KPI 카드용 집계. 모두 SQL 에서 계산한다."""
    with conn.cursor() as cur:
        cur.execute(
            "select (select avg(oee) from v_oee_daily),"
            "       (select sum(defect_qty)::numeric / nullif(sum(input_qty), 0) from v_defect_rate),"
            "       (select count(*) from v_equipment_current where status = 'RUN'),"
            "       (select count(*) from v_equipment_current)")
        oee, defect, running, total = cur.fetchone()
    return {"avg_oee": None if oee is None else float(oee),
            "defect_rate": None if defect is None else float(defect),
            "running": running, "total": total}

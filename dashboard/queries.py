"""대시보드용 조회 함수. 각 함수는 뷰/함수에 대한 SELECT 한 개만 실행한다.

KPI 계산은 전부 SQL(뷰) 쪽에서 끝나며, 여기서는 DataFrame 으로 옮기고
Decimal -> float 변환만 한다. 정렬도 SQL 의 ORDER BY 로 정한다.
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

# OEE 집계 범위: 데이터가 있는 가장 최근 교대 창과 그 직전 교대(= 최근 24시간, 2교대).
# 진행 중인 교대는 뷰에서 계획시간이 now() 까지로 잘려 있으므로 그대로 포함한다.
# 시뮬레이션 시작 무렵의 일부만 덮인 교대처럼 오래된 행이 평균을 왜곡하지 않게 한다.
RECENT_OEE = ("shift_end > (select max(shift_end) from v_oee_daily) - interval '24 hours'")


def _frame(conn, sql, columns, params=None, floats=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=columns)
    for c in floats:
        df[c] = df[c].astype(float)
    return df


def oee_by_equipment(conn) -> pd.DataFrame:
    """설비별 최근 2교대 평균 OEE/가동률/성능률/품질률 (집계는 SQL), 라인 → 공정 순서."""
    return _frame(
        conn,
        "select o.equipment_name, avg(o.oee), avg(o.availability), avg(o.performance), avg(o.quality)"
        " from v_oee_daily o join equipment e using (equipment_id) join process p using (process_id)"
        f" where {RECENT_OEE}"
        " group by o.equipment_name, e.line_id, p.seq order by e.line_id, p.seq",
        OEE_COLS, floats=OEE_COLS[1:])


def wo_progress(conn) -> pd.DataFrame:
    """진행 중(RUNNING) → 대기(PLANNED) → 완료(DONE, 최근 것부터) 순."""
    return _frame(conn, f"select {', '.join(WO_COLS)} from v_wo_progress"
                        " order by case status when 'RUNNING' then 0 when 'PLANNED' then 1 else 2 end,"
                        " case when status = 'DONE' then -wo_id else wo_id end",
                  WO_COLS, floats=["progress_pct"])


def defect_by_process(conn) -> pd.DataFrame:
    return _frame(conn, "select " + ", ".join(f"d.{c}" for c in DEFECT_COLS) +
                  " from v_defect_rate d join process p on p.code = d.process_code order by p.seq",
                  DEFECT_COLS, floats=["defect_rate", "fty"])


def equipment_status(conn) -> pd.DataFrame:
    """설비 현재 상태, 라인 → 공정 순서."""
    return _frame(conn, "select " + ", ".join(f"c.{c}" for c in EQUIP_COLS) +
                  " from v_equipment_current c join equipment e using (equipment_id)"
                  " join process p using (process_id) order by e.line_id, p.seq",
                  EQUIP_COLS)


def lot_trace(conn, lot_no: str, direction: str) -> pd.DataFrame:
    if direction not in TRACE_COLS:
        raise ValueError(f"direction must be 'forward' or 'backward', got {direction!r}")
    cols = TRACE_COLS[direction]
    fn = "trace_forward" if direction == "forward" else "trace_backward"
    return _frame(conn, f"select {', '.join(cols)} from {fn}(%s) order by depth, lot_no",
                  cols, params=(lot_no,))


def kpi_summary(conn) -> dict:
    """상단 KPI 카드용 집계. 모두 SQL 에서 계산한다. 평균 OEE 는 최근 2교대 설비x교대 행의 평균."""
    with conn.cursor() as cur:
        cur.execute(
            f"select (select avg(oee) from v_oee_daily where {RECENT_OEE}),"
            "       (select sum(defect_qty)::numeric / nullif(sum(input_qty), 0) from v_defect_rate),"
            "       (select count(*) from v_equipment_current where status = 'RUN'),"
            "       (select count(*) from v_equipment_current)")
        oee, defect, running, total = cur.fetchone()
    return {"avg_oee": None if oee is None else float(oee),
            "defect_rate": None if defect is None else float(defect),
            "running": running, "total": total}

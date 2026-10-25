"""조회 엔드포인트. 지표 계산은 전부 SQL(뷰/함수)에서 끝나고, 여기서는 SELECT 와 직렬화만 한다."""
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from backend.app.deps import get_conn
from backend.app.schemas import (
    DefectRow, Equipment, EquipmentDetail, Kpi, Lookups, OeeEquipment, StatusLogRow,
    TraceBackRow, TraceRow, WoOptions, WorkOrder, WorkOrderDetail,
)

router = APIRouter(prefix="/api")

# OEE 집계 범위: 데이터가 있는 가장 최근 교대 창과 그 직전 교대(= 최근 24시간, 2교대).
RECENT_OEE = "shift_end > (select max(shift_end) from v_oee_daily) - interval '24 hours'"

EQUIPMENT_SQL = (
    "select c.equipment_id, c.name, e.line_id, l.name as line_name, e.process_id,"
    "       p.code as process_code, p.name as process_name, p.seq as process_seq,"
    "       c.status, c.since,"
    "       case when c.status <> 'RUN' then dr.name end as reason"
    " from v_equipment_current c"
    " join equipment e using (equipment_id)"
    " join line l using (line_id)"
    " join process p using (process_id)"
    " left join lateral (select reason_id from equipment_status_log sl"
    "                    where sl.equipment_id = c.equipment_id"
    "                    order by sl.started_at desc, sl.log_id desc limit 1) last on true"
    " left join downtime_reason dr on dr.reason_id = last.reason_id"
)

WO_SQL = (
    "select w.wo_id, w.item_code, i.name as item_name, l.name as line_name,"
    "       w.planned_qty, w.good_qty, w.progress_pct, w.status, w.due_date"
    " from v_wo_progress w"
    " join work_order wo using (wo_id)"
    " join item i on i.item_id = wo.item_id"
    " join line l on l.line_id = wo.line_id"
)
WO_ORDER = (
    " order by case w.status when 'RUNNING' then 0 when 'PLANNED' then 1 else 2 end,"
    " w.wo_id desc"
)


def _all(conn: psycopg.Connection, sql: str, params=None) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _one(conn: psycopg.Connection, sql: str, params=None) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


@router.get("/kpi", response_model=Kpi)
def kpi(conn=Depends(get_conn)):
    return _one(
        conn,
        f"select (select avg(oee) from v_oee_daily where {RECENT_OEE}) as avg_oee,"
        "  (select sum(defect_qty)::numeric / nullif(sum(input_qty), 0) from v_defect_rate)"
        "    as defect_rate,"
        "  (select count(*) from v_equipment_current where status = 'RUN') as running_equipment,"
        "  (select count(*) from v_equipment_current) as total_equipment")


@router.get("/oee/equipment", response_model=list[OeeEquipment])
def oee_equipment(conn=Depends(get_conn)):
    return _all(
        conn,
        "select o.equipment_name, avg(o.oee) as oee, avg(o.availability) as availability,"
        "       avg(o.performance) as performance, avg(o.quality) as quality"
        " from v_oee_daily o join equipment e using (equipment_id) join process p using (process_id)"
        f" where {RECENT_OEE}"
        " group by o.equipment_name, e.line_id, p.seq order by e.line_id, p.seq")


@router.get("/defects", response_model=list[DefectRow])
def defects(conn=Depends(get_conn)):
    return _all(
        conn,
        "select d.process_code, d.input_qty, d.defect_qty, d.scrap_qty, d.rework_qty,"
        "       d.defect_rate, d.fty"
        " from v_defect_rate d join process p on p.code = d.process_code order by p.seq")


@router.get("/equipment", response_model=list[Equipment])
def equipment_list(conn=Depends(get_conn)):
    return _all(conn, EQUIPMENT_SQL + " order by e.line_id, p.seq")


@router.get("/equipment/{equipment_id}", response_model=EquipmentDetail)
def equipment_detail(equipment_id: int, conn=Depends(get_conn)):
    row = _one(conn, EQUIPMENT_SQL + " where c.equipment_id = %s", (equipment_id,))
    if row is None:
        raise HTTPException(404, "설비를 찾을 수 없습니다")
    row["recent_oee"] = _all(
        conn,
        "select shift_name, work_date, availability, performance, quality, oee,"
        "       shift_start, shift_end"
        " from v_oee_daily where equipment_id = %s order by shift_end desc limit 6",
        (equipment_id,))
    row["recent_results"] = _all(
        conn,
        "select result_id, wo_id, good_qty, defect_qty, ended_at from production_result"
        " where equipment_id = %s order by ended_at desc, result_id desc limit 10",
        (equipment_id,))
    return row


@router.get("/equipment/{equipment_id}/status-log", response_model=list[StatusLogRow])
def status_log(equipment_id: int, limit: int = Query(50, ge=1, le=500), conn=Depends(get_conn)):
    return _all(
        conn,
        "select sl.status, dr.name as reason, sl.started_at, sl.ended_at"
        " from equipment_status_log sl left join downtime_reason dr using (reason_id)"
        " where sl.equipment_id = %s order by sl.started_at desc, sl.log_id desc limit %s",
        (equipment_id, limit))


@router.get("/work-orders", response_model=list[WorkOrder])
def work_orders(status: Literal["PLANNED", "RUNNING", "DONE"] | None = None,
                conn=Depends(get_conn)):
    where, params = ("", None) if status is None else (" where w.status = %s", (status,))
    return _all(conn, WO_SQL + where + WO_ORDER, params)


@router.get("/work-orders/{wo_id}", response_model=WorkOrderDetail)
def work_order_detail(wo_id: int, conn=Depends(get_conn)):
    row = _one(conn, WO_SQL + " where w.wo_id = %s", (wo_id,))
    if row is None:
        raise HTTPException(404, "작업지시를 찾을 수 없습니다")
    row["processes"] = _all(
        conn,
        "select p.code as process_code, p.seq as process_seq,"
        "       coalesce(sum(pr.good_qty), 0) as good_qty,"
        "       coalesce(sum(pr.defect_qty), 0) as defect_qty"
        " from work_order wo"
        " join routing rt on rt.item_id = wo.item_id"
        " join process p on p.process_id = rt.process_id"
        " left join production_result pr on pr.wo_id = wo.wo_id and pr.process_id = p.process_id"
        " where wo.wo_id = %s group by p.code, p.seq order by p.seq",
        (wo_id,))
    row["lots"] = _all(
        conn,
        "select lt.lot_no, p.code as process_code, lt.qty, lt.created_at"
        " from lot lt left join process p on p.process_id = lt.process_id"
        " where lt.wo_id = %s order by lt.created_at desc, lt.lot_id desc",
        (wo_id,))
    return row


@router.get("/lookups", response_model=Lookups)
def lookups(conn=Depends(get_conn)):
    return {
        "items": _all(conn, "select item_id, item_code, name, item_type from item"
                            " where item_type in ('FG', 'SFG') order by item_type, item_code"),
        "lines": _all(conn, "select line_id, name from line order by line_id"),
        "processes": _all(conn, "select process_id, code, name, seq from process order by seq"),
        "reasons": _all(conn, "select reason_id, name, is_planned from downtime_reason"
                              " order by reason_id"),
        "defect_codes": _all(conn, "select defect_id, name from defect_code order by defect_id"),
    }


@router.get("/work-orders/{wo_id}/options", response_model=WoOptions)
def work_order_options(wo_id: int, conn=Depends(get_conn)):
    wo = _one(conn, "select wo_id, status, item_id, line_id from work_order where wo_id = %s",
              (wo_id,))
    if wo is None:
        raise HTTPException(404, "작업지시를 찾을 수 없습니다")
    procs = _all(
        conn,
        "select p.process_id, p.code, p.name, p.seq from routing rt"
        " join process p using (process_id) where rt.item_id = %s order by p.seq",
        (wo["item_id"],))
    eqs = _all(conn, "select equipment_id, process_id, name from equipment"
                     " where line_id = %s order by equipment_id", (wo["line_id"],))
    for p in procs:
        p["equipment"] = [{"equipment_id": e["equipment_id"], "name": e["name"]}
                          for e in eqs if e["process_id"] == p["process_id"]]
    return {"wo_id": wo["wo_id"], "status": wo["status"], "processes": procs}


@router.get("/lots/{lot_no}/trace")
def lot_trace(lot_no: str, direction: str, conn=Depends(get_conn)):
    if direction == "forward":
        rows = _all(conn, "select lot_no, item_code, depth from trace_forward(%s)"
                          " order by depth, lot_no", (lot_no,))
        return [TraceRow(**r) for r in rows]
    if direction == "backward":
        rows = _all(conn, "select lot_no, item_code, supplier_lot_no, depth"
                          " from trace_backward(%s) order by depth, lot_no", (lot_no,))
        return [TraceBackRow(**r) for r in rows]
    raise HTTPException(400, "direction 은 forward 또는 backward 여야 합니다")

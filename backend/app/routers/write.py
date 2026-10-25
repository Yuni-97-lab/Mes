"""입력 엔드포인트: 작업지시 생성, 생산실적 입력, 설비 상태 변경. 커밋은 get_conn 이 한다."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.app.deps import get_conn
from backend.app.errors import translate_db_error
from backend.app.routers.read import EQUIPMENT_SQL, _one
from backend.app.schemas import (
    Equipment, ResultCreated, ResultIn, StatusIn, WorkOrderCreated, WorkOrderIn,
)
from backend.app.services.results import create_result

KST = timezone(timedelta(hours=9), "KST")
router = APIRouter(prefix="/api")


@router.post("/work-orders", status_code=201, response_model=WorkOrderCreated)
def create_work_order(body: WorkOrderIn, conn=Depends(get_conn)):
    item = conn.execute("SELECT item_type FROM item WHERE item_id = %s", (body.item_id,)).fetchone()
    if item is None or item[0] not in ("FG", "SFG"):
        raise HTTPException(422, "완제품 또는 반제품만 작업지시를 만들 수 있습니다")
    if conn.execute("SELECT 1 FROM line WHERE line_id = %s", (body.line_id,)).fetchone() is None:
        raise HTTPException(422, "존재하지 않는 라인입니다")
    wo_id = conn.execute(
        "INSERT INTO work_order (item_id, line_id, planned_qty, due_date) VALUES (%s,%s,%s,%s)"
        " RETURNING wo_id", (body.item_id, body.line_id, body.planned_qty, body.due_date)).fetchone()[0]
    return {"wo_id": wo_id}


@router.post("/results", status_code=201, response_model=ResultCreated)
def post_result(body: ResultIn, conn=Depends(get_conn)):
    try:
        result_id, lot_no = create_result(conn, body, datetime.now(KST))
    except HTTPException:
        raise
    except Exception as e:
        raise translate_db_error(e) or e
    return {"result_id": result_id, "lot_no": lot_no}


@router.post("/equipment/{equipment_id}/status", response_model=Equipment)
def change_status(equipment_id: int, body: StatusIn, conn=Depends(get_conn)):
    if conn.execute("SELECT 1 FROM equipment WHERE equipment_id = %s", (equipment_id,)).fetchone() is None:
        raise HTTPException(404, "설비를 찾을 수 없습니다")
    if body.status == "DOWN" and body.reason_id is None:
        raise HTTPException(422, "DOWN 상태에는 사유가 필요합니다")
    if body.reason_id is not None and conn.execute(
            "SELECT 1 FROM downtime_reason WHERE reason_id = %s", (body.reason_id,)).fetchone() is None:
        raise HTTPException(422, "존재하지 않는 비가동 사유입니다")
    open_log = conn.execute(
        "SELECT log_id, status, reason_id, started_at FROM equipment_status_log"
        " WHERE equipment_id = %s AND ended_at IS NULL FOR UPDATE", (equipment_id,)).fetchone()
    now = datetime.now(KST)
    if open_log is None or (open_log[1], open_log[2]) != (body.status, body.reason_id):
        if open_log is not None:
            now = max(now, open_log[3])   # ended_at >= started_at 제약 보호
            conn.execute("UPDATE equipment_status_log SET ended_at = %s WHERE log_id = %s",
                         (now, open_log[0]))
        conn.execute("INSERT INTO equipment_status_log (equipment_id, status, reason_id, started_at)"
                     " VALUES (%s,%s,%s,%s)", (equipment_id, body.status, body.reason_id, now))
    return _one(conn, EQUIPMENT_SQL + " where c.equipment_id = %s", (equipment_id,))

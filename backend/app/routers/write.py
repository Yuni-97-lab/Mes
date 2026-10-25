"""입력 엔드포인트: 작업지시 생성, 생산실적 입력, 설비 상태 변경.

커밋은 get_conn 이 한다. 쓰기 엔드포인트는 Depends(get_conn, scope="function") 이라 핸들러가 끝나면
응답을 보내기 *전에* commit 한다 (기본 "request" 스코프는 응답 전송 후 commit → 커밋 실패해도 사용자는 성공을 봄).
DB 예외는 translate_db_error 로 HTTP 오류(409 등)로 바꾼다.
"""
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

import psycopg
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
T = TypeVar("T")


def write_conn():
    return Depends(get_conn, scope="function")


def _translated(fn: Callable[[], T]) -> T:
    """fn 실행 중 DB 예외를 HTTP 오류로 변환 (HTTPException 은 그대로)."""
    try:
        return fn()
    except HTTPException:
        raise
    except psycopg.Error as e:
        raise translate_db_error(e) or e


@router.post("/work-orders", status_code=201, response_model=WorkOrderCreated)
def create_work_order(body: WorkOrderIn, conn=write_conn()):
    item = conn.execute("SELECT item_type FROM item WHERE item_id = %s", (body.item_id,)).fetchone()
    if item is None or item[0] not in ("FG", "SFG"):
        raise HTTPException(422, "완제품 또는 반제품만 작업지시를 만들 수 있습니다")
    if conn.execute("SELECT 1 FROM line WHERE line_id = %s", (body.line_id,)).fetchone() is None:
        raise HTTPException(422, "존재하지 않는 라인입니다")
    wo_id = _translated(lambda: conn.execute(
        "INSERT INTO work_order (item_id, line_id, planned_qty, due_date) VALUES (%s,%s,%s,%s)"
        " RETURNING wo_id", (body.item_id, body.line_id, body.planned_qty, body.due_date)).fetchone()[0])
    return {"wo_id": wo_id}


@router.post("/results", status_code=201, response_model=ResultCreated)
def post_result(body: ResultIn, conn=write_conn()):
    result_id, lot_no = _translated(lambda: create_result(conn, body, datetime.now(KST)))
    return {"result_id": result_id, "lot_no": lot_no}


def _apply_status(conn, equipment_id: int, body: StatusIn) -> None:
    """열린 로그를 잠그고(FOR UPDATE) 닫은 뒤 새 로그를 연다. savepoint 안에서 실행되어 실패 시 전부 롤백."""
    open_log = conn.execute(
        "SELECT log_id, status, reason_id, started_at FROM equipment_status_log"
        " WHERE equipment_id = %s AND ended_at IS NULL FOR UPDATE", (equipment_id,)).fetchone()
    now = datetime.now(KST)
    if open_log is None or (open_log[1], open_log[2]) != (body.status, body.reason_id):
        if open_log is not None:
            now = max(now, open_log[3])   # ended_at >= started_at 제약 보호
            conn.execute("UPDATE equipment_status_log SET ended_at = %s WHERE log_id = %s",
                         (now, open_log[0]))
        # 동시에 시뮬레이터가 새 열린 로그를 만들었다면 유일 인덱스 위반 -> 409 (다시 시도)
        conn.execute("INSERT INTO equipment_status_log (equipment_id, status, reason_id, started_at)"
                     " VALUES (%s,%s,%s,%s)", (equipment_id, body.status, body.reason_id, now))


@router.post("/equipment/{equipment_id}/status", response_model=Equipment)
def change_status(equipment_id: int, body: StatusIn, conn=write_conn()):
    if conn.execute("SELECT 1 FROM equipment WHERE equipment_id = %s", (equipment_id,)).fetchone() is None:
        raise HTTPException(404, "설비를 찾을 수 없습니다")
    if body.status == "DOWN" and body.reason_id is None:
        raise HTTPException(422, "DOWN 상태에는 사유가 필요합니다")
    if body.reason_id is not None and conn.execute(
            "SELECT 1 FROM downtime_reason WHERE reason_id = %s", (body.reason_id,)).fetchone() is None:
        raise HTTPException(422, "존재하지 않는 비가동 사유입니다")

    def apply():
        with conn.transaction():
            _apply_status(conn, equipment_id, body)

    _translated(apply)
    return _one(conn, EQUIPMENT_SQL + " where c.equipment_id = %s", (equipment_id,))

"""수동 생산실적 입력. 시뮬레이터(_insert_result)와 같은 LOT 계보 규칙을 쓴다.

커밋하지 않는다. 삽입은 savepoint(conn.transaction()) 안에서 하므로 실패하면 LOT·계보·실적이 모두 롤백된다.
DB 예외(CheckViolation 등)는 그대로 전파하며 호출자가 translate_db_error 로 변환한다.
"""
import random
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import HTTPException

from backend.app.schemas import ResultIn
from simulator.simulate import _context, _shift_id, lineage_parents

KST = timezone(timedelta(hours=9), "KST")


def _lot_no(conn: psycopg.Connection, wo_id: int, pcode: str) -> str:
    """WO-<wo>-<공정코드>-M<n>: n = 기존 …-M% LOT 수 + 1, 이미 있으면 빈 번호까지 올린다."""
    prefix = f"WO-{wo_id}-{pcode}-M"
    n = conn.execute("SELECT count(*) FROM lot WHERE lot_no LIKE %s", (prefix + "%",)).fetchone()[0] + 1
    while conn.execute("SELECT 1 FROM lot WHERE lot_no = %s", (prefix + str(n),)).fetchone():
        n += 1
    return prefix + str(n)


def _validate(conn: psycopg.Connection, p: ResultIn, ctx: dict) -> tuple[int, int, int | None]:
    """422/404 검증. 반환 (item_id, 라우팅 인덱스, 직전 공정 id)."""
    wo = conn.execute("SELECT item_id, line_id, status FROM work_order WHERE wo_id = %s", (p.wo_id,)).fetchone()
    if wo is None:
        raise HTTPException(404, "작업지시를 찾을 수 없습니다")
    eq = conn.execute("SELECT line_id, process_id FROM equipment WHERE equipment_id = %s",
                      (p.equipment_id,)).fetchone()
    if eq is None:
        raise HTTPException(404, "설비를 찾을 수 없습니다")
    item_id, line_id, status = wo
    if status == "DONE":
        raise HTTPException(422, "이미 완료된 작업지시에는 실적을 입력할 수 없습니다")
    if not 0 < p.minutes <= 60:
        raise HTTPException(422, "작업 시간(분)은 0 초과 60 이하여야 합니다")
    stages = ctx["routing"].get(item_id, [])
    idx = next((i for i, (pid, _) in enumerate(stages) if pid == p.process_id), None)
    if idx is None:
        raise HTTPException(422, "작업지시의 라우팅에 없는 공정입니다")
    if eq[0] != line_id:
        raise HTTPException(422, "설비가 작업지시의 라인에 속하지 않습니다")
    if eq[1] != p.process_id:
        raise HTTPException(422, "설비가 선택한 공정의 설비가 아닙니다")
    if p.good_qty == 0 and not p.defects:
        raise HTTPException(422, "양품 수량 또는 불량 내역이 필요합니다")
    known = set(ctx["defect_ids"])
    if any(d.defect_id not in known for d in p.defects):
        raise HTTPException(422, "존재하지 않는 불량 코드입니다")
    return item_id, idx, stages[idx - 1][0] if idx > 0 else None


def create_result(conn: psycopg.Connection, payload: ResultIn, now: datetime) -> tuple[int, str]:
    """실적 1건과 LOT·계보·불량내역을 적재한다. 반환 (result_id, lot_no)."""
    ctx = _context(conn)
    item_id, idx, prev_process = _validate(conn, payload, ctx)
    ended = now
    started = now - timedelta(minutes=payload.minutes)
    shift_id = _shift_id(ctx["shifts"], now.astimezone(KST))
    pcode = ctx["pcodes"][payload.process_id]

    defects: dict[tuple[int, str], int] = {}   # (불량코드, 구분)별 합산: defect_record PK 충돌 방지
    for d in payload.defects:
        defects[(d.defect_id, d.kind)] = defects.get((d.defect_id, d.kind), 0) + d.qty
    defect_qty = sum(defects.values())
    rework_qty = sum(q for (_, kind), q in defects.items() if kind == "rework")
    qty_in = payload.good_qty + defect_qty

    with conn.transaction():
        lot_no = _lot_no(conn, payload.wo_id, pcode)
        lot_id = conn.execute(
            "INSERT INTO lot (lot_no, item_id, wo_id, process_id, qty, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING lot_id",
            (lot_no, item_id, payload.wo_id, payload.process_id, payload.good_qty, ended)).fetchone()[0]
        for parent_id, q in lineage_parents(conn, ctx, payload.wo_id, item_id, idx, prev_process,
                                            qty_in, started, random.Random()):
            conn.execute("INSERT INTO lot_consumption (parent_lot_id, child_lot_id, qty) VALUES (%s,%s,%s)",
                         (parent_id, lot_id, q))
        result_id = conn.execute(
            "INSERT INTO production_result (wo_id, process_id, equipment_id, shift_id, lot_id, started_at,"
            " ended_at, good_qty, defect_qty, rework_qty) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " RETURNING result_id",
            (payload.wo_id, payload.process_id, payload.equipment_id, shift_id, lot_id, started, ended,
             payload.good_qty, defect_qty, rework_qty)).fetchone()[0]
        for (defect_id, kind), q in defects.items():
            conn.execute("INSERT INTO defect_record (result_id, defect_id, kind, qty) VALUES (%s,%s,%s,%s)",
                         (result_id, defect_id, kind, q))
    return result_id, lot_no

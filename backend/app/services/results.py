"""수동 생산실적 입력. 시뮬레이터(_insert_result)와 같은 LOT 계보 규칙을 쓴다.

커밋하지 않는다. 작업지시 잠금·검증·삽입은 savepoint(conn.transaction()) 안에서 하므로 실패(422 포함)하면 LOT·계보·실적이 모두 롤백된다.
후공정은 전공정 재공(직전 공정 누적 양품 - 이 공정 누적 투입)까지만 입력할 수 있다.
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
    prev_process = stages[idx - 1][0] if idx > 0 else None
    if prev_process is not None:
        available = _upstream_wip(conn, p.wo_id, prev_process, p.process_id)
        if p.good_qty + sum(d.qty for d in p.defects) > available:
            raise HTTPException(422, f"전공정 재공이 부족합니다 (가능 수량: {available})")
    return item_id, idx, prev_process


def _upstream_wip(conn: psycopg.Connection, wo_id: int, prev_process: int, process_id: int) -> int:
    """후공정 투입 가능 수량 = 직전 공정 누적 양품 - 이 공정 누적 투입(양품+불량). 시뮬레이터 _find_work 와 같은 식."""
    prev_good, here_in = conn.execute(
        "SELECT COALESCE(sum(good_qty) FILTER (WHERE process_id = %s), 0),"
        "       COALESCE(sum(good_qty + defect_qty) FILTER (WHERE process_id = %s), 0)"
        " FROM production_result WHERE wo_id = %s", (prev_process, process_id, wo_id)).fetchone()
    return max(0, int(prev_good - here_in))


def create_result(conn: psycopg.Connection, payload: ResultIn, now: datetime) -> tuple[int, str]:
    """실적 1건과 LOT·계보·불량내역을 적재한다. 반환 (result_id, lot_no)."""
    ctx = _context(conn)
    ended = now
    started = now - timedelta(minutes=payload.minutes)
    shift_id = _shift_id(ctx["shifts"], now.astimezone(KST))
    pcode = ctx["pcodes"].get(payload.process_id)

    defects: dict[tuple[int, str], int] = {}   # (불량코드, 구분)별 합산: defect_record PK 충돌 방지
    for d in payload.defects:
        defects[(d.defect_id, d.kind)] = defects.get((d.defect_id, d.kind), 0) + d.qty
    defect_qty = sum(defects.values())
    rework_qty = sum(q for (_, kind), q in defects.items() if kind == "rework")
    qty_in = payload.good_qty + defect_qty

    with conn.transaction():
        # 같은 작업지시의 동시 입력을 직렬화: 재공 검사·LOT 번호(count+1)·계보 할당이 서로 경쟁하지 않게
        # LOT 을 만들기 전에 작업지시 행을 잠근다 (트리거의 잠금은 실적 INSERT 시점이라 너무 늦다).
        conn.execute("SELECT 1 FROM work_order WHERE wo_id = %s FOR UPDATE", (payload.wo_id,))
        item_id, idx, prev_process = _validate(conn, payload, ctx)
        lot_no = _lot_no(conn, payload.wo_id, pcode)
        lot_id = conn.execute(
            "INSERT INTO lot (lot_no, item_id, wo_id, process_id, qty, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING lot_id",
            (lot_no, item_id, payload.wo_id, payload.process_id, payload.good_qty, ended)).fetchone()[0]
        parents = lineage_parents(conn, ctx, payload.wo_id, item_id, idx, prev_process,
                                  qty_in, started, random.Random())
        if idx > 0 and sum(q for _, q in parents) < qty_in:
            # 방어 검사: 실적 수량상 재공은 있어도 전공정 LOT 잔량이 모자라면 계보가 끊긴 LOT 이 생기므로 거부
            raise HTTPException(422, "전공정 LOT 잔량이 부족하여 계보를 연결할 수 없습니다")
        for parent_id, q in parents:
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

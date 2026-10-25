"""공장 시뮬레이터: 작업지시 생성, 설비 상태 전이, 생산실적/불량/LOT 적재.

시뮬레이션 시계: step(conn, now, ...) 은 구간 [now - tick_seconds, now] 한 틱을 진행한다.
  상태 전이는 틱 시작 시각에 일어나고, RUN 설비는 그 틱 동안 생산한다.
  시뮬 시각은 모두 KST(Asia/Seoul, UTC+9 고정, 서머타임 없음) 기준이다. DB 세션도 같은 시간대다(mes.db).
CLI 시계 규칙 (main): 시뮬 시각은 벽시계(현재 시각)를 절대 넘지 않는다.
  - 틱 길이 = --tick x --speed (시뮬 초).
  - 시작점: 빈 DB 에서 --once N 은 "지금 - N틱" 부터(마지막 틱이 지금), 연속 모드는 현재 교대 시작부터.
    DB 에 데이터가 있으면 마지막 시각부터 이어 간다. 너무 오래 멈춰 있었으면(마지막 시각이 시작점 이전)
    마지막 시각에 설비를 정지(IDLE) 처리하고 시작점부터 새로 채운다.
  - 연속 모드: 벽시계보다 뒤처져 있는 동안은 실시간 --tick 초마다 한 틱(= --speed 배속으로 따라잡기),
    따라잡은 뒤에는 벽시계가 다음 틱 시각에 닿을 때까지 기다린다(실시간 진행).
  - --once N: 최대 N틱을 기다림 없이 실행하되 벽시계에 닿으면 그 자리에서 끝낸다.
  - 종료(정상 종료, Ctrl+C) 시 진행 중 로그를 마지막 시뮬 시각에 닫고 IDLE 로 남겨, 멈춘 동안 RUN 시간이 쌓이지 않게 한다.
    다음 실행의 첫 틱에서 그 정지 로그를 닫아(resume_equipment) 설비가 바로 가동을 재개한다.
트랜잭션: step/ensure_work_orders/replenish/park_equipment 는 커밋하지 않는다. 커밋은 호출자(CLI 루프·테스트) 책임.
상태는 모두 DB(설비 최신 상태 로그, 진행 중 작업지시)에 있으므로 재시작해도 이어서 동작한다.
난수는 전부 인자로 받은 random.Random 에서만 뽑아 같은 seed·같은 DB 상태면 같은 결과를 낸다.
"""
import argparse
import math
import random
import time
from datetime import datetime, timedelta, timezone

import psycopg.errors

from mes.db import connect

KST = timezone(timedelta(hours=9), "KST")

# RUN 에서의 상태 전이 빈도(시뮬 1시간당 평균 발생 횟수). 틱 길이에 맞춰 틱당 확률로 바꾼다.
RATE_PER_HOUR = {"DOWN": 0.12, "IDLE": 0.4, "MAINT": 0.03, "LUNCH": 3.0}
# 정지 상태별 (최소 유지 초, 최소 시간 이후 평균 추가 지속 초). 사유 이름이 키에 없으면 상태(IDLE/DOWN)로 찾는다.
RECOVERY = {
    "IDLE": (120, 300),
    "DOWN": (600, 1200),
    "점심": (2700, 300),
    "정기점검": (1800, 900),
}
STARVED = "자재대기"            # 일감(작업지시·전공정 재공·자재)이 없을 때의 비계획 IDLE 사유
PERF_RANGE = (0.75, 0.98)       # 이상 사이클 대비 실제 속도 -> OEE 성능률
# 공정별 실적 불량률 범위: 검사 공정(AOI, 기능검사)에서 불량이 주로 검출된다
DEFECT_RATE = {
    "MATIN": (0.002, 0.01), "SMT": (0.01, 0.03), "AOI": (0.04, 0.07),
    "ASM": (0.01, 0.025), "FCT": (0.04, 0.07), "PACK": (0.002, 0.01),
}
WIP_MARGIN = 1.15               # 마지막 이전 공정은 계획의 115% 까지 생산(후공정 수율 손실 보전)
RM_LOW, RM_REFILL = 20000, 500000
RM_LOT_SIZE = 10000             # 원자재 공급사 LOT 1개 수량 (여러 작업지시가 선입선출로 나눠 씀)


def _p(rate_per_hour, seconds):
    """시간당 발생률을 seconds 길이 틱에서의 발생 확률로 변환."""
    return 1 - math.exp(-rate_per_hour * seconds / 3600)


# ---------------------------------------------------------------- 작업지시
def ensure_work_orders(conn, min_running: int = 3, rng: random.Random | None = None,
                       now: datetime | None = None) -> int:
    """라인마다 PLANNED/RUNNING 상태의 SFG 작업지시와 FG 작업지시가 하나 이상 있도록 보충한다.

    SFG 라우팅(자재투입→SMT→AOI)과 FG 라우팅(조립→기능검사→포장)은 공정이 겹치지 않으므로,
    라인의 6개 설비 모두에 일감이 생기려면 라인마다 두 종류가 다 있어야 한다.
    그래도 전체 진행 중 작업지시가 min_running 미만이면 임의 품목·라인으로 더 만든다.
    반제품은 (재고 + 진행 중 계획수량)이 가장 적은 품목을 고른다(간단한 소요량 계획).
    now: 시뮬 시각. 작업지시 created_at 과 납기(due_date = now + 2~5일)의 기준. 없으면 현재 시각.
    생성 건수를 반환하며, 이미 충족되어 있으면 0 (멱등) 이므로 재시작해도 중복 생성되지 않는다.
    """
    rng = rng or random.Random()
    base = (now or datetime.now(KST)).astimezone(KST)
    items = conn.execute("SELECT item_id, item_type FROM item WHERE item_type IN ('FG','SFG') "
                         "ORDER BY item_id").fetchall()
    by_type = {t: [i for i, it in items if it == t] for t in ("SFG", "FG")}
    lines = [r[0] for r in conn.execute("SELECT line_id FROM line ORDER BY line_id")]

    def active():
        return conn.execute(
            "SELECT wo.line_id, i.item_type FROM work_order wo JOIN item i USING (item_id) "
            "WHERE wo.status IN ('PLANNED','RUNNING')").fetchall()

    def pick_sfg():
        return conn.execute("""
            SELECT i.item_id FROM item i JOIN inventory v USING (item_id)
            WHERE i.item_type = 'SFG'
            ORDER BY v.qty + COALESCE((SELECT sum(wo.planned_qty) FROM work_order wo
                                       WHERE wo.item_id = i.item_id AND wo.status IN ('PLANNED','RUNNING')), 0),
                     i.item_id LIMIT 1""").fetchone()[0]

    def create(item_id, line_id):
        conn.execute(
            "INSERT INTO work_order (item_id, line_id, planned_qty, due_date, created_at) "
            "VALUES (%s,%s,%s,%s, COALESCE(%s, now()))",
            (item_id, line_id, rng.randint(200, 800),
             base.date() + timedelta(days=rng.randint(2, 5)), now))

    created = 0
    have = set(active())
    for line_id in lines:
        for typ in ("SFG", "FG"):
            if (line_id, typ) not in have:
                create(pick_sfg() if typ == "SFG" else rng.choice(by_type["FG"]), line_id)
                created += 1
    total = len(active())
    while total < min_running:
        create(rng.choice([i for i, _ in items]), rng.choice(lines))
        created += 1
        total += 1
    return created


# ---------------------------------------------------------------- 설비 상태
def _shift_id(shifts, at):
    """시각 at(KST)이 속한 교대(야간은 자정을 넘김)."""
    t = at.astimezone(KST).time()
    for sid, start, end in shifts:
        if (start <= end and start <= t < end) or (start > end and (t >= start or t < end)):
            return sid
    return shifts[0][0]


def _shift_start(shifts, at):
    """시각 at(KST)이 속한 교대 창의 시작 시각."""
    at = at.astimezone(KST)
    sid = _shift_id(shifts, at)
    start_time = next(s for i, s, _ in shifts if i == sid)
    start = datetime.combine(at.date(), start_time, KST)
    return start - timedelta(days=1) if start > at else start


def _set_state(conn, eid, prev_log_id, at, status, reason_id):
    """이전 로그를 at 에 닫고 새 로그를 at 에 연다 (설비당 열린 로그는 항상 1개)."""
    if prev_log_id is not None:
        conn.execute("UPDATE equipment_status_log SET ended_at = %s WHERE log_id = %s", (at, prev_log_id))
    return conn.execute("INSERT INTO equipment_status_log (equipment_id, status, reason_id, started_at) "
                        "VALUES (%s,%s,%s,%s) RETURNING log_id", (eid, status, reason_id, at)).fetchone()[0]


def _transition(conn, ctx, eid, prev, t0, rng, dt, has_work):
    """틱 시작 시각 t0 의 상태 전이. 반환: (log_id, status, 현재 상태 시작시각).

    - 일감이 없으면 RUN 대신 IDLE(자재대기)로 둔다. 자재대기 중 일감이 생기면 바로 RUN.
    - RUN 중에는 시간당 발생률로 고장(DOWN 설비고장)·순간정지(IDLE)·정기점검·점심(12~13시)이 일어난다.
    - 그 외 정지는 최소 유지시간 이후 확률적으로 복귀(일감 없으면 자재대기로).
    """
    reasons = ctx["reasons"]
    starved = (reasons[STARVED], "IDLE")
    run_or_wait = ("RUN", None) if has_work else ("IDLE", reasons[STARVED])
    if prev is None:   # 로그 없는 설비: 틱 시작부터 가동(또는 자재대기)
        st, rid = run_or_wait
        return _set_state(conn, eid, None, t0, st, rid), st, t0
    log_id, status, reason_id, started, ended = prev
    t = max(t0, started, ended or started)   # 시계가 되돌아가도 로그가 겹치지 않게
    name = ctx["reason_name"].get(reason_id)
    new = None   # (status, reason_id)
    if ended is not None:   # 닫혀 있는 최신 로그(비정상 상태): 재개
        new = run_or_wait
    elif status == "RUN":
        lunch = 12 <= t0.astimezone(KST).hour < 13
        r = rng.random()
        if lunch and rng.random() < _p(RATE_PER_HOUR["LUNCH"], dt):
            new = ("IDLE", reasons["점심"])                    # 계획 정지
        elif r < (pd := _p(RATE_PER_HOUR["DOWN"], dt)):
            new = ("DOWN", reasons["설비고장"])                 # 비계획 고장
        elif r < (pi := pd + _p(RATE_PER_HOUR["IDLE"], dt)):
            new = ("IDLE", None)                               # 순간정지
        elif r < pi + _p(RATE_PER_HOUR["MAINT"], dt):
            new = ("DOWN", reasons["정기점검"])                 # 계획 정지
        elif not has_work:
            new = run_or_wait
    elif (reason_id, status) == starved:
        if has_work:
            new = ("RUN", None)
    else:
        min_sec, mean = RECOVERY[name if name in RECOVERY else status]
        if (t - started).total_seconds() >= min_sec and rng.random() < 1 - math.exp(-dt / mean):
            new = run_or_wait
    if new is None or (ended is None and new == (status, reason_id)):
        return log_id, status, started
    return _set_state(conn, eid, None if ended is not None else log_id, t, *new), new[0], t


# ---------------------------------------------------------------- 일감 / LOT
def _find_work(conn, ctx, line_id, process_id):
    """설비(라인, 공정)가 지금 처리할 수 있는 작업지시. 반환 (wo_id, item_id, 라우팅 순번, 투입 가능 수량) 또는 None.

    투입 가능 수량: 첫 공정은 계획 x 115%(마지막 공정이면 100%)와 BOM 자재 재고로 만들 수 있는 양,
    후공정은 직전 공정 누적 양품 - 이 공정 누적 투입(양품+불량), 마지막 공정은 계획 - 누적 양품 도 넘지 않음.
    """
    for wo_id, item_id, planned in conn.execute(
            "SELECT wo_id, item_id, planned_qty FROM work_order "
            "WHERE line_id=%s AND status IN ('PLANNED','RUNNING') ORDER BY wo_id", (line_id,)).fetchall():
        stages = ctx["routing"].get(item_id, [])
        idx = next((i for i, (p, _) in enumerate(stages) if p == process_id), None)
        if idx is None:
            continue
        done = {p: (float(g), float(n)) for p, g, n in conn.execute(
            "SELECT process_id, sum(good_qty), sum(good_qty + defect_qty) FROM production_result "
            "WHERE wo_id=%s GROUP BY process_id", (wo_id,))}
        planned = float(planned)
        good_here, input_here = done.get(process_id, (0.0, 0.0))
        last = idx == len(stages) - 1
        headroom = (planned - good_here) if last else (planned * WIP_MARGIN - good_here)
        if idx == 0:   # 자재 재고로 만들 수 있는 만큼
            for child_id, qty_per in ctx["bom"].get(item_id, []):
                stock = float(conn.execute("SELECT COALESCE((SELECT qty FROM inventory WHERE item_id=%s), 0)",
                                           (child_id,)).fetchone()[0])
                headroom = min(headroom, stock // qty_per)
        else:          # 전공정에서 넘어온 재공만큼
            headroom = min(headroom, done.get(stages[idx - 1][0], (0.0, 0.0))[0] - input_here)
        headroom = int(headroom)
        if headroom > 0:
            return wo_id, item_id, idx, headroom
    return None


def _fifo(conn, where, params, need):
    """조건에 맞는 LOT 중 잔량(수량 - 이미 투입된 양)이 있는 것을 오래된 순으로 need 만큼 할당. [(lot_id, 수량)]."""
    out = []
    for lot_id, remain in conn.execute(f"""
            SELECT lot_id, remain FROM (
                SELECT l.lot_id, l.qty - COALESCE((SELECT sum(c.qty) FROM lot_consumption c
                                                   WHERE c.parent_lot_id = l.lot_id), 0) AS remain
                FROM lot l WHERE {where}) t
            WHERE remain > 0 ORDER BY lot_id""", params).fetchall():
        if need <= 0:
            break
        take = min(float(remain), need)
        out.append((lot_id, take))
        need -= take
    return out, need


def _rm_parents(conn, child_id, child_code, need, at, rng):
    """원자재 LOT 선입선출 할당. 잔량이 모자라면 새 공급사 LOT(입고)를 만든다. 번호: <품목코드>-<순번 4자리>."""
    out, short = _fifo(conn, "l.item_id = %s AND l.wo_id IS NULL", (child_id,), need)
    if short > 0:
        # 시뮬레이터와 수동 입력(API)이 동시에 공급사 LOT 을 만들면 같은 count+1 번호를 쓰게 되므로
        # 트랜잭션 단위 advisory lock 으로 입고 LOT 생성을 직렬화한다 (커밋/롤백 시 자동 해제).
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('mes.rm_lot_no'))")
    while short > 0:
        n = conn.execute("SELECT count(*) FROM lot WHERE item_id=%s AND wo_id IS NULL",
                         (child_id,)).fetchone()[0] + 1
        while conn.execute("SELECT 1 FROM lot WHERE lot_no = %s", (f"{child_code}-{n:04d}",)).fetchone():
            n += 1   # 이미 쓰인 번호는 건너뜀
        size = max(RM_LOT_SIZE, short)
        lot_id = conn.execute(
            "INSERT INTO lot (lot_no, item_id, supplier_lot_no, qty, created_at) VALUES (%s,%s,%s,%s,%s) "
            "RETURNING lot_id",
            (f"{child_code}-{n:04d}", child_id, f"SUP-{rng.randint(100000, 999999)}", size, at)).fetchone()[0]
        take = min(size, short)
        out.append((lot_id, take))
        short -= take
    return out


def lineage_parents(conn, ctx, wo_id, item_id, routing_idx, prev_process, qty_in, started, rng):
    """생성 LOT 의 투입(부모) LOT 할당 [(lot_id, 수량)]. 시뮬레이터와 수동 실적 입력(API)이 공유한다.

    첫 공정(routing_idx == 0): BOM 자식별로 소요량(qty_per x 투입수) 선입선출.
      원자재는 공급사 LOT, 반제품은 그 품목 라우팅 "마지막 공정"(완성 반제품) LOT 중 잔량 있는 것.
    이후 공정: 같은 작업지시의 바로 앞 공정(prev_process) LOT 중 잔량 있는 것을 선입선출.
    """
    parents = []
    if routing_idx == 0:
        for child_id, qty_per in ctx["bom"].get(item_id, []):
            need = qty_per * qty_in
            if ctx["item_type"][child_id] == "RM":
                parents += _rm_parents(conn, child_id, ctx["item_code"][child_id], need, started, rng)
            else:
                finished = ctx["routing"][child_id][-1][0]
                parents += _fifo(conn, "l.item_id = %s AND l.process_id = %s AND l.wo_id IS NOT NULL",
                                 (child_id, finished), need)[0]
    else:
        parents += _fifo(conn, "l.wo_id = %s AND l.process_id = %s", (wo_id, prev_process), qty_in)[0]
    return parents


def _insert_result(conn, ctx, wo, eq, routing_idx, good, defect, shift_id, started, ended, rng):
    """LOT·실적·불량내역·LOT 계보를 한 번에 적재한다 (호출자가 savepoint 로 감싼다).

    계보(lot_consumption, 투입 LOT -> 생성 LOT, 수량 = 실제 투입량):
      첫 공정  : BOM 자식별로 소요량(qty_per x 투입수)만큼 선입선출 할당.
                 원자재는 공급사 LOT, 반제품은 그 품목 라우팅 "마지막 공정"(완성 반제품) LOT 중 잔량 있는 것.
      이후 공정: 같은 작업지시의 바로 앞 공정 LOT 중 잔량 있는 것을 선입선출.
    """
    wo_id, item_id = wo
    equipment_id, process_id, pcode = eq["id"], eq["process_id"], eq["code"]
    qty_in = good + defect
    seq = conn.execute("SELECT count(*) FROM lot WHERE wo_id=%s AND process_id=%s",
                       (wo_id, process_id)).fetchone()[0] + 1
    lot_id = conn.execute(
        "INSERT INTO lot (lot_no, item_id, wo_id, process_id, qty, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING lot_id",
        (f"WO-{wo_id}-{pcode}-{seq}", item_id, wo_id, process_id, good, ended)).fetchone()[0]

    parents = lineage_parents(conn, ctx, wo_id, item_id, routing_idx, eq["prev_process"], qty_in, started, rng)
    for pid, q in parents:
        conn.execute("INSERT INTO lot_consumption (parent_lot_id, child_lot_id, qty) VALUES (%s,%s,%s)",
                     (pid, lot_id, q))

    rework = rng.randint(0, defect) if defect else 0
    result_id = conn.execute(
        "INSERT INTO production_result (wo_id, process_id, equipment_id, shift_id, lot_id, started_at, "
        "ended_at, good_qty, defect_qty, rework_qty) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "RETURNING result_id",
        (wo_id, process_id, equipment_id, shift_id, lot_id, started, ended, good, defect, rework)
    ).fetchone()[0]
    for kind, qty in (("rework", rework), ("scrap", defect - rework)):
        if qty > 0:
            conn.execute("INSERT INTO defect_record (result_id, defect_id, kind, qty) VALUES (%s,%s,%s,%s)",
                         (result_id, rng.choice(ctx["defect_ids"]), kind, qty))


def _context(conn):
    ctx = {
        "shifts": conn.execute("SELECT shift_id, start_time, end_time FROM shift ORDER BY shift_id").fetchall(),
        "defect_ids": [r[0] for r in conn.execute("SELECT defect_id FROM defect_code ORDER BY defect_id")],
        "pcodes": dict(conn.execute("SELECT process_id, code FROM process").fetchall()),
        "routing": {}, "bom": {}, "item_type": {}, "item_code": {},
    }
    for item_id, pid, ideal in conn.execute(
            "SELECT item_id, process_id, ideal_cycle_sec FROM routing ORDER BY item_id, seq"):
        ctx["routing"].setdefault(item_id, []).append((pid, float(ideal)))
    for parent, child, qty_per in conn.execute(
            "SELECT parent_item_id, child_item_id, qty_per FROM bom ORDER BY parent_item_id, child_item_id"):
        ctx["bom"].setdefault(parent, []).append((child, float(qty_per)))
    for item_id, code, typ in conn.execute("SELECT item_id, item_code, item_type FROM item"):
        ctx["item_type"][item_id], ctx["item_code"][item_id] = typ, code
    ctx["reasons"] = dict(conn.execute("SELECT name, reason_id FROM downtime_reason").fetchall())
    ctx["reason_name"] = {v: k for k, v in ctx["reasons"].items()}
    return ctx


def step(conn, now: datetime, rng: random.Random, tick_seconds: float = 60) -> int:
    """한 틱 [now - tick_seconds, now] 진행. 적재한 실적 행 수를 반환한다.

    설비를 라인 → 공정 순으로 돌며: 일감 확인 → 틱 시작 시각의 상태 전이 → RUN 이면 생산(_produce).
    틱이 교대 경계를 걸치면 경계에서 실적을 나눈다(실적 교대 = 실적 시작 시각의 교대).
    투입 가능 수량이 먼저 바닥나면 그 시각에 RUN 을 끝내고 IDLE(자재대기)로 바꾼다 (일감 없는 RUN 시간 없음).
    재고 부족(CheckViolation)·초과생산/재고 행 없음(RaiseException)은 savepoint 롤백으로 해당 실적만 건너뛴다.
    API 와의 동시 실행: 열린 상태 로그를 잠근 뒤 읽고, 그래도 열린 로그 충돌(UniqueViolation)이 나면 그 설비만 이번 틱을 건너뛴다.
    """
    ctx = _context(conn)
    t0 = now - timedelta(seconds=tick_seconds)
    # 이번 틱에 닫을 수 있는 열린 로그를 먼저 잠근다: API 상태 변경과 동시에 실행되면 한쪽이 커밋할 때까지 기다리고,
    # 잠근 뒤 읽으므로 상대가 커밋한 최신 로그를 본다 (READ COMMITTED: 문장마다 새 스냅샷).
    conn.execute("SELECT log_id FROM equipment_status_log WHERE ended_at IS NULL ORDER BY log_id FOR UPDATE")
    latest = {r[0]: r[1:] for r in conn.execute("""
        SELECT DISTINCT ON (equipment_id) equipment_id, log_id, status, reason_id, started_at, ended_at
        FROM equipment_status_log ORDER BY equipment_id, started_at DESC, log_id DESC""")}
    equipments = conn.execute(
        "SELECT e.equipment_id, e.line_id, e.process_id FROM equipment e JOIN process p USING (process_id) "
        "ORDER BY e.line_id, p.seq").fetchall()
    inserted = 0
    for eid, line_id, process_id in equipments:
        work = _find_work(conn, ctx, line_id, process_id)
        try:
            with conn.transaction():   # 설비별 savepoint: 충돌 시 이 설비의 전이만 롤백
                log_id, status, since = _transition(conn, ctx, eid, latest.get(eid), t0, rng, tick_seconds,
                                                    work is not None)
        except psycopg.errors.UniqueViolation:
            continue   # 다른 쓰기(API 상태 변경)가 먼저 열린 로그를 만듦: 이 설비는 이번 틱을 건너뛰고 다음 틱에 최신 로그로 이어 감
        if status != "RUN" or work is None:
            continue
        wo_id, item_id, idx, headroom = work
        stages = ctx["routing"][item_id]
        eq = {"id": eid, "process_id": process_id, "code": ctx["pcodes"][process_id],
              "prev_process": stages[idx - 1][0] if idx > 0 else None}
        seg = max(t0, since)
        while seg < now and headroom > 0:   # 교대 경계에서 실적을 나눠 각 교대 OEE 에 정확히 귀속
            stop = min(now, _next_shift_start(ctx["shifts"], seg))
            n, end = _produce(conn, ctx, eq, (wo_id, item_id), idx, headroom, seg, stop, rng)
            inserted += n > 0
            headroom -= n
            if end < stop:   # 일감 소진(또는 적재 실패): 남은 시간은 자재대기
                _set_state(conn, eid, log_id, end, "IDLE", ctx["reasons"][STARVED])
                break
            seg = stop
    return inserted


def _next_shift_start(shifts, at):
    """at 이후(초과) 가장 가까운 교대 시작 시각."""
    at = at.astimezone(KST)
    return min(c for _, s, _ in shifts for d in (0, 1)
               if (c := datetime.combine(at.date() + timedelta(days=d), s, KST)) > at)


def _produce(conn, ctx, eq, wo, idx, headroom, start, stop, rng):
    """[start, stop] 구간 생산 실적 1건. 반환 (투입 수량, 가동 종료 시각).

    생산량 = 구간 길이 x 속도(PERF_RANGE) / 이상 사이클 (확률적 반올림), headroom 을 넘지 않음.
    headroom 에 먼저 닿으면 가동 종료 시각이 stop 보다 앞선다. 적재 실패 시 (0, stop): RUN 유지, 다음 틱에 재시도.
    """
    cycle = ctx["routing"][wo[1]][idx][1]
    perf = rng.uniform(*PERF_RANGE)
    cap = (stop - start).total_seconds() * perf / cycle
    cap = int(cap) + (1 if rng.random() < cap - int(cap) else 0)   # 확률적 반올림(짧은 틱에서도 편향 없음)
    qty = min(headroom, cap)
    if qty <= 0:
        return 0, stop
    end = stop if qty == cap else start + timedelta(seconds=qty * cycle / perf)
    rate = rng.uniform(*DEFECT_RATE.get(eq["code"], (0.02, 0.05)))
    defect = sum(1 for _ in range(qty) if rng.random() < rate)
    try:
        with conn.transaction():
            _insert_result(conn, ctx, wo, eq, idx, qty - defect, defect,
                           _shift_id(ctx["shifts"], start), start, end, rng)
    except (psycopg.errors.CheckViolation, psycopg.errors.RaiseException, psycopg.errors.UniqueViolation):
        return 0, stop   # 재고 부족/초과생산/동시 입력과의 번호 충돌: 이 실적만 건너뜀 (다음 틱에 재시도)
    return qty, end


def replenish(conn) -> int:
    """원자재 재고가 임계치 미만이면 입고 처리(수불 원장 + 재고 갱신). 입고한 품목 수 반환. step 과 분리."""
    low = conn.execute("SELECT i.item_id FROM item i JOIN inventory v USING (item_id) "
                       "WHERE i.item_type='RM' AND v.qty < %s ORDER BY i.item_id", (RM_LOW,)).fetchall()
    for (item_id,) in low:
        conn.execute("INSERT INTO inventory_txn (item_id, delta) VALUES (%s,%s)", (item_id, RM_REFILL))
        conn.execute("UPDATE inventory SET qty = qty + %s WHERE item_id=%s", (RM_REFILL, item_id))
    return len(low)


def park_equipment(conn, at: datetime) -> int:
    """시뮬레이터 정지 처리: 진행 중 로그를 at 에 닫고 사유 없는 IDLE 로그를 연다. 처리한 설비 수 반환.

    이미 사유 없는 IDLE 인 설비는 건드리지 않는다(멱등). 멈춘 동안 RUN(또는 계획 정지) 시간이 쌓이지 않게 한다.
    """
    rows = conn.execute("""SELECT log_id, equipment_id, started_at FROM equipment_status_log
                           WHERE ended_at IS NULL AND NOT (status = 'IDLE' AND reason_id IS NULL)
                           ORDER BY equipment_id FOR UPDATE""").fetchall()
    for log_id, eid, started in rows:
        _set_state(conn, eid, log_id, max(at, started), "IDLE", None)
    return len(rows)


def resume_equipment(conn, at: datetime) -> int:
    """시뮬레이터 재개 처리: 정지(사유 없는 IDLE) 로그를 at 에 닫는다. 닫은 로그 수 반환.

    최신 로그가 닫혀 있으면 다음 틱에서 바로 RUN(일감 없으면 자재대기)으로 시작한다.
    정지 구간 [정지 시각, at] 은 IDLE 로 남아 가동률에 반영된다.
    """
    return conn.execute("""UPDATE equipment_status_log SET ended_at = greatest(%s, started_at)
                           WHERE ended_at IS NULL AND status = 'IDLE' AND reason_id IS NULL""", (at,)).rowcount


# ---------------------------------------------------------------- CLI 시계
def clock_wait(target: datetime, wall: datetime, pause: float) -> float:
    """시뮬 시각 target 의 틱을 실행하기 전에 기다릴 실시간(초).

    target 이 벽시계보다 미래면 벽시계가 target 에 닿을 때까지 기다린다 → 시뮬 시각은 벽시계를 넘지 않는다.
    이미 지났으면(따라잡는 중) pause(--tick) 만큼만 쉰다 → --speed 배속으로 따라잡는다.
    """
    ahead = (target - wall).total_seconds()
    return ahead if ahead > 0 else pause


def resume_point(last: datetime | None, wall: datetime, dt: float, once: int | None, shifts):
    """시뮬 시작 시각과 공백 여부 (start, gap).

    기본 시작점: --once N 이면 wall - N틱, 연속 모드면 현재 교대 시작. DB 마지막 시각이 그 이후면 거기서 이어 가고
    (단 wall 을 넘지 않음), 그보다 이전이면 공백(gap=True): 마지막 시각에 설비를 정지 처리하고 기본 시작점부터 채운다.
    """
    base = wall - timedelta(seconds=dt * once) if once else _shift_start(shifts, wall)
    if last is None:
        return min(base, wall), False
    if last >= base:
        return min(last, wall), False
    return base, True


def _latest_db_time(conn):
    return conn.execute("""SELECT greatest((SELECT max(started_at) FROM equipment_status_log),
                                           (SELECT max(ended_at) FROM equipment_status_log),
                                           (SELECT max(ended_at) FROM production_result))""").fetchone()[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description="MES 공장 시뮬레이터 (시뮬 시각은 현재 시각을 넘지 않음)")
    ap.add_argument("--speed", type=float, default=60,
                    help="틱 길이 = --tick x --speed 시뮬 초. 뒤처져 있을 때 따라잡는 배속 (60 = 실 1초당 시뮬 1분)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--once", type=int, default=None, metavar="N",
                    help="최대 N 틱을 기다림 없이 실행 후 종료 (현재 시각에 닿으면 더 일찍 끝남)")
    ap.add_argument("--tick", type=float, default=1.0, help="따라잡는 동안의 실시간 틱 간격(초)")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    dt = args.tick * args.speed   # 틱당 시뮬 경과 초
    with connect() as conn:
        shifts = conn.execute("SELECT shift_id, start_time, end_time FROM shift ORDER BY shift_id").fetchall()
        last = _latest_db_time(conn)
        sim, gap = resume_point(last, datetime.now(KST), dt, args.once, shifts)
        if gap:   # 오래 멈춰 있던 DB: 멈춘 시각에 설비 정지 처리 후 새 시작점부터
            park_equipment(conn, last)
            conn.commit()
            print(f"[{last:%Y-%m-%d %H:%M:%S}] 이전 실행 이후 공백 -> 설비 정지 처리, {sim:%Y-%m-%d %H:%M} 부터 재개")
        n = 0
        try:
            while args.once is None or n < args.once:
                target = sim + timedelta(seconds=dt)
                if args.once is not None:
                    if target > datetime.now(KST):
                        print("현재 시각에 도달하여 종료")
                        break
                else:
                    time.sleep(clock_wait(target, datetime.now(KST), args.tick))
                if n == 0:   # 재개: 이전 실행의 정지 로그를 닫아 첫 틱부터 바로 가동
                    resume_equipment(conn, sim)
                created = ensure_work_orders(conn, 3, rng, now=sim)
                replenish(conn)
                rows = step(conn, target, rng, tick_seconds=dt)
                conn.commit()
                sim = target
                n += 1
                print(f"[{sim:%Y-%m-%d %H:%M:%S}] tick={n} 실적={rows} 신규작업지시={created}", flush=True)
        except KeyboardInterrupt:
            conn.rollback()
            print("중단됨")
        finally:
            if not conn.closed:
                conn.rollback()
                park_equipment(conn, sim)   # 멈춘 동안 RUN 시간이 쌓이지 않게
                conn.commit()


if __name__ == "__main__":
    main()

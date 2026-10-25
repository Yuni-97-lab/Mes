"""공장 시뮬레이터: 작업지시 생성, 설비 상태 전이, 생산실적/불량/LOT 적재.

시뮬레이션 시계: step() 은 시각 `now`(tz-aware)에서 한 틱을 진행한다. CLI 는 실시간 틱마다
`tick_seconds * speed` 만큼 시뮬 시간을 전진시킨다.
트랜잭션: step/ensure_work_orders/replenish 는 커밋하지 않는다. 커밋은 호출자(CLI 루프·테스트) 책임.
상태는 모두 DB(설비 최신 상태 로그, 진행 중 작업지시)에 있으므로 재시작해도 이어서 동작한다.
난수는 전부 인자로 받은 random.Random 에서만 뽑아 같은 seed·같은 DB 상태면 같은 결과를 낸다.
"""
import argparse
import random
import time
from datetime import datetime, timedelta

import psycopg.errors

from mes.db import connect

# 상태별 (최소 유지 초, 틱당 복귀 확률). 최소 시간이 지난 뒤 확률적으로 RUN 복귀.
RECOVERY = {
    "IDLE": (180, 0.4),
    "DOWN": (600, 0.25),
    "점심": (2700, 0.5),
    "정기점검": (1800, 0.3),
}
# RUN 에서의 틱당 전이 확률
P_IDLE, P_DOWN, P_MAINT, P_LUNCH = 0.02, 0.01, 0.002, 0.03
MAX_BATCH = 60                  # 한 사이클 최대 생산 개수
PERF_RANGE = (0.75, 0.98)       # 이상 사이클 대비 실제 속도 -> OEE 성능률
DEFECT_RATE = (0.02, 0.05)      # 실적별 불량률
WIP_MARGIN = 1.15               # 마지막 이전 공정은 계획의 115% 까지 생산(후공정 수율 손실 보전)
RM_LOW, RM_REFILL = 20000, 500000


# ---------------------------------------------------------------- 작업지시
def ensure_work_orders(conn, min_running: int = 3, rng: random.Random | None = None) -> int:
    """PLANNED/RUNNING 작업지시가 min_running 미만이면 부족분만큼 새로 만들고 생성 수를 반환한다.

    SFG 작업지시가 하나도 없으면 먼저 SFG 를 만들어 FG 조립에 쓸 반제품 재고가 생기게 한다.
    이미 충분하면 0 을 반환하므로(멱등) 재시작해도 중복 생성되지 않는다.
    """
    rng = rng or random.Random()
    active = conn.execute(
        "SELECT count(*) FROM work_order WHERE status IN ('PLANNED','RUNNING')").fetchone()[0]
    need = max(0, min_running - active)
    if need == 0:
        return 0
    items = conn.execute("SELECT item_id, item_type FROM item WHERE item_type IN ('FG','SFG') "
                         "ORDER BY item_id").fetchall()
    lines = [r[0] for r in conn.execute("SELECT line_id FROM line ORDER BY line_id")]
    has_sfg = conn.execute(
        "SELECT count(*) FROM work_order wo JOIN item i USING (item_id) "
        "WHERE wo.status IN ('PLANNED','RUNNING') AND i.item_type = 'SFG'").fetchone()[0] > 0
    for _ in range(need):
        pool = items if has_sfg else [i for i in items if i[1] == "SFG"]
        item_id = rng.choice(pool)[0]
        has_sfg = True
        conn.execute(
            "INSERT INTO work_order (item_id, line_id, planned_qty, due_date) VALUES (%s,%s,%s,%s)",
            (item_id, rng.choice(lines), rng.randint(200, 800),
             (datetime.now() + timedelta(days=rng.randint(2, 5))).date()))
    return need


# ---------------------------------------------------------------- 설비 상태
def _shift_id(shifts, now):
    """now 의 시각이 속한 교대(야간은 자정을 넘김)."""
    t = now.time()
    for sid, start, end in shifts:
        if (start <= end and start <= t < end) or (start > end and (t >= start or t < end)):
            return sid
    return shifts[0][0]


def _update_equipment_states(conn, now, rng, tick_seconds):
    """설비별 상태 전이. 이전 로그는 닫고(ended_at) 새 로그를 열어 비중첩을 유지한다.

    반환: {equipment_id: (status, 현재 상태 시작시각)}
    """
    reasons = {n: (rid, planned) for rid, n, planned in conn.execute(
        "SELECT reason_id, name, is_planned FROM downtime_reason")}
    unplanned = sorted(rid for rid, p in reasons.values() if not p)
    latest = {r[0]: r for r in conn.execute("""
        SELECT DISTINCT ON (equipment_id) equipment_id, log_id, status, reason_id, started_at, ended_at
        FROM equipment_status_log ORDER BY equipment_id, started_at DESC, log_id DESC""")}
    name_of = {rid: n for n, (rid, _) in reasons.items()}
    state = {}
    for (eid,) in conn.execute("SELECT equipment_id FROM equipment ORDER BY equipment_id").fetchall():
        prev = latest.get(eid)
        if prev is None:  # 로그 없는 설비는 RUN 으로 시작 (직전 틱부터 가동 중이었던 것으로 기록)
            start = now - timedelta(seconds=tick_seconds)
            conn.execute("INSERT INTO equipment_status_log (equipment_id, status, started_at) "
                         "VALUES (%s,'RUN',%s)", (eid, start))
            state[eid] = ("RUN", start)
            continue
        _, log_id, status, reason_id, started, ended = prev
        t = max(now, started, ended or started)   # 시계가 되돌아가도 로그가 겹치지 않게
        new = None   # (status, reason_id)
        if ended is not None:   # 닫혀 있는 최신 로그(비정상 상태): RUN 재개
            new = ("RUN", None)
        elif status == "RUN":
            r = rng.random()
            if 12 <= now.hour < 13 and r < P_LUNCH:
                new = ("IDLE", reasons["점심"][0])   # 점심 시간대 계획 정지
            elif r < P_DOWN:
                new = ("DOWN", rng.choice(unplanned))   # 비계획 고장/자재대기
            elif r < P_DOWN + P_IDLE:
                new = ("IDLE", None)
            elif r < P_DOWN + P_IDLE + P_MAINT:
                new = ("DOWN", reasons["정기점검"][0])
        else:
            key = name_of.get(reason_id)
            key = key if key in RECOVERY else status
            min_sec, p = RECOVERY[key]
            if (t - started).total_seconds() >= min_sec and rng.random() < p:
                new = ("RUN", None)
        if new is None:
            state[eid] = (status, started)
            continue
        if ended is None:
            conn.execute("UPDATE equipment_status_log SET ended_at = %s WHERE log_id = %s", (t, log_id))
        conn.execute("INSERT INTO equipment_status_log (equipment_id, status, reason_id, started_at) "
                     "VALUES (%s,%s,%s,%s)", (eid, new[0], new[1], t))
        state[eid] = (new[0], t)
    return state


# ---------------------------------------------------------------- 생산
def _insert_result(conn, wo, eq, routing_idx, good, defect, shift_id, started, ended, rng, defect_ids):
    """LOT·실적·불량내역·LOT 계보를 한 번에 적재한다 (호출자가 savepoint 로 감싼다)."""
    wo_id, item_id = wo
    equipment_id, process_id, pcode = eq["id"], eq["process_id"], eq["code"]
    seq = conn.execute("SELECT count(*) FROM lot WHERE wo_id=%s AND process_id=%s",
                       (wo_id, process_id)).fetchone()[0] + 1
    lot_id = conn.execute(
        "INSERT INTO lot (lot_no, item_id, wo_id, process_id, qty, created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING lot_id",
        (f"WO-{wo_id}-{pcode}-{seq}", item_id, wo_id, process_id, good, ended)).fetchone()[0]

    # 계보 부모 LOT 결정: 첫 공정이면 BOM 자식(RM 은 작업지시당 1개 재사용, SFG 는 최신 LOT),
    # 이후 공정이면 같은 작업지시의 직전 공정 최신 LOT
    parents = []
    if routing_idx == 0:
        for child_id, child_code, ctype in conn.execute(
                "SELECT i.item_id, i.item_code, i.item_type FROM bom b JOIN item i ON i.item_id=b.child_item_id "
                "WHERE b.parent_item_id=%s ORDER BY i.item_id", (item_id,)).fetchall():
            if ctype == "RM":
                lot_no = f"RM-{child_code}-WO{wo_id}"
                row = conn.execute("SELECT lot_id FROM lot WHERE lot_no=%s", (lot_no,)).fetchone()
                if row is None:
                    row = conn.execute(
                        "INSERT INTO lot (lot_no, item_id, supplier_lot_no, qty, created_at) "
                        "VALUES (%s,%s,%s,%s,%s) RETURNING lot_id",
                        (lot_no, child_id, f"SUP-{rng.randint(100000, 999999)}", 100000, ended)).fetchone()
                parents.append(row[0])
            else:
                row = conn.execute("SELECT max(lot_id) FROM lot WHERE item_id=%s AND wo_id IS NOT NULL",
                                   (child_id,)).fetchone()
                if row[0] is not None:
                    parents.append(row[0])
    else:
        row = conn.execute("SELECT max(lot_id) FROM lot WHERE wo_id=%s AND lot_id<>%s AND process_id=%s",
                           (wo_id, lot_id, eq["prev_process"])).fetchone()
        if row[0] is not None:
            parents.append(row[0])
    for pid in parents:
        conn.execute("INSERT INTO lot_consumption (parent_lot_id, child_lot_id, qty) VALUES (%s,%s,%s)",
                     (pid, lot_id, good + defect))

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
                         (result_id, rng.choice(defect_ids), kind, qty))


def step(conn, now: datetime, rng: random.Random, tick_seconds: float = 60) -> int:
    """한 틱 진행: 설비 상태 전이 후 RUN 설비마다 실적 1건 적재. 적재한 실적 행 수를 반환한다.

    재고 부족(CheckViolation)·초과생산(RaiseException)은 savepoint 롤백으로 해당 실적만 건너뛴다.
    """
    shifts = conn.execute("SELECT shift_id, start_time, end_time FROM shift ORDER BY shift_id").fetchall()
    shift_id = _shift_id(shifts, now)
    defect_ids = [r[0] for r in conn.execute("SELECT defect_id FROM defect_code ORDER BY defect_id")]
    routing = {}   # item_id -> [(process_id, ideal_cycle_sec)] 공정 순
    for item_id, pid, ideal in conn.execute(
            "SELECT item_id, process_id, ideal_cycle_sec FROM routing ORDER BY item_id, seq"):
        routing.setdefault(item_id, []).append((pid, float(ideal)))
    pcodes = dict(conn.execute("SELECT process_id, code FROM process").fetchall())

    state = _update_equipment_states(conn, now, rng, tick_seconds)
    equipments = conn.execute(
        "SELECT equipment_id, line_id, process_id FROM equipment ORDER BY equipment_id").fetchall()
    inserted = 0
    for eid, line_id, process_id in equipments:
        status, since = state[eid]
        if status != "RUN":
            continue
        start = max(now - timedelta(seconds=tick_seconds), since)
        dur = (now - start).total_seconds()
        if dur <= 0:
            continue
        for wo_id, item_id, planned in conn.execute(
                "SELECT wo_id, item_id, planned_qty FROM work_order "
                "WHERE line_id=%s AND status IN ('PLANNED','RUNNING') ORDER BY wo_id", (line_id,)).fetchall():
            stages = routing.get(item_id, [])
            idx = next((i for i, (p, _) in enumerate(stages) if p == process_id), None)
            if idx is None:
                continue
            good_by = {p: float(g) for p, g in conn.execute(
                "SELECT process_id, sum(good_qty) FROM production_result WHERE wo_id=%s GROUP BY process_id",
                (wo_id,))}
            planned = float(planned)
            done_here = good_by.get(process_id, 0.0)
            last = idx == len(stages) - 1
            headroom = (planned if last else planned * WIP_MARGIN) - done_here
            if idx > 0:   # 후공정은 직전 공정의 누적 양품까지만
                headroom = min(headroom, good_by.get(stages[idx - 1][0], 0.0) - done_here)
            headroom = int(headroom)
            if headroom <= 0:
                continue
            perf = rng.uniform(*PERF_RANGE)
            qty = min(headroom, max(1, min(MAX_BATCH, int(dur * perf / stages[idx][1]))))
            rate = rng.uniform(*DEFECT_RATE)
            defect = sum(1 for _ in range(qty) if rng.random() < rate)
            eq = {"id": eid, "process_id": process_id, "code": pcodes[process_id],
                  "prev_process": stages[idx - 1][0] if idx > 0 else None}
            try:
                with conn.transaction():
                    _insert_result(conn, (wo_id, item_id), eq, idx, qty - defect, defect,
                                   shift_id, start, now, rng, defect_ids)
                inserted += 1
            except (psycopg.errors.CheckViolation, psycopg.errors.RaiseException):
                pass   # 재고 부족/초과생산: 이 실적만 건너뜀 (다음 틱에 재시도)
            break      # 설비는 틱당 한 작업지시만 처리
    return inserted


def replenish(conn) -> int:
    """원자재 재고가 임계치 미만이면 입고 처리(수불 원장 + 재고 갱신). 입고한 품목 수 반환. step 과 분리."""
    low = conn.execute("SELECT i.item_id FROM item i JOIN inventory v USING (item_id) "
                       "WHERE i.item_type='RM' AND v.qty < %s ORDER BY i.item_id", (RM_LOW,)).fetchall()
    for (item_id,) in low:
        conn.execute("INSERT INTO inventory_txn (item_id, delta) VALUES (%s,%s)", (item_id, RM_REFILL))
        conn.execute("UPDATE inventory SET qty = qty + %s WHERE item_id=%s", (RM_REFILL, item_id))
    return len(low)


# ---------------------------------------------------------------- CLI
def _latest_db_time(conn):
    return conn.execute("""SELECT greatest((SELECT max(started_at) FROM equipment_status_log),
                                           (SELECT max(ended_at) FROM production_result))""").fetchone()[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description="MES 공장 시뮬레이터")
    ap.add_argument("--speed", type=float, default=60, help="시뮬 시간/실시간 배율 (60 = 실 1초당 시뮬 1분)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--once", type=int, default=None, metavar="N", help="N 틱 실행 후 종료")
    ap.add_argument("--tick", type=float, default=1.0, help="실시간 틱 간격(초)")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    dt = args.tick * args.speed   # 틱당 시뮬 경과 초
    with connect() as conn:
        now_real = datetime.now().astimezone()
        # --once 는 마지막 틱이 현재 시각이 되도록 과거부터 채운다. 재시작 시 DB 의 마지막 시각 이후부터 이어간다.
        sim = now_real - timedelta(seconds=dt * args.once) if args.once else now_real
        last = _latest_db_time(conn)
        if last is not None and last > sim:
            sim = last
        n = 0
        try:
            while args.once is None or n < args.once:
                sim += timedelta(seconds=dt)
                created = ensure_work_orders(conn, 3, rng)
                replenish(conn)
                rows = step(conn, sim, rng, tick_seconds=dt)
                conn.commit()
                n += 1
                print(f"[{sim:%Y-%m-%d %H:%M:%S}] tick={n} 실적={rows} 신규작업지시={created}", flush=True)
                if args.once is None:
                    time.sleep(args.tick)
        except KeyboardInterrupt:
            conn.rollback()
            print("중단됨")


if __name__ == "__main__":
    main()

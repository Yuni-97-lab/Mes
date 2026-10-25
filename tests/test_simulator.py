"""시뮬레이터 테스트: 결정성, 재시작 멱등성, 불량 합계, 재고 고갈, 계획수량, 로그 비중첩."""
import random
from datetime import datetime, timedelta, timezone

from simulator.simulate import ensure_work_orders, step

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=KST)  # 주간조, 점심 이전


def _run(conn, seed, steps, tick=60):
    rng = random.Random(seed)
    ensure_work_orders(conn, 3, rng)
    total = 0
    for i in range(steps):
        total += step(conn, T0 + timedelta(seconds=tick * i), rng, tick_seconds=tick)
    return total


def _scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_step_inserts_results_and_respects_seed(seeded_db):
    conn = seeded_db
    conn.execute("SAVEPOINT s0")
    a = _run(conn, 42, 20)
    conn.execute("ROLLBACK TO SAVEPOINT s0")
    b = _run(conn, 42, 20)
    assert a > 0
    assert a == b


def test_restart_does_not_duplicate_work_orders(seeded_db):
    conn = seeded_db
    rng = random.Random(1)
    assert ensure_work_orders(conn, 3, rng) == 3
    assert ensure_work_orders(conn, 3, rng) == 0
    assert _scalar(conn, "SELECT count(*) FROM work_order WHERE status IN ('PLANNED','RUNNING')") == 3


def test_defect_records_sum_matches_result(seeded_db):
    conn = seeded_db
    _run(conn, 7, 40)
    assert _scalar(conn, "SELECT count(*) FROM production_result") > 0
    bad = conn.execute("""
        SELECT pr.result_id FROM production_result pr
        LEFT JOIN defect_record d ON d.result_id = pr.result_id
        GROUP BY pr.result_id, pr.defect_qty, pr.rework_qty
        HAVING pr.defect_qty <> COALESCE(sum(d.qty), 0)
            OR pr.rework_qty <> COALESCE(sum(d.qty) FILTER (WHERE d.kind = 'rework'), 0)
    """).fetchall()
    assert bad == []
    assert _scalar(conn, "SELECT count(*) FROM production_result WHERE defect_qty > 0") > 0


def test_stock_exhaustion_does_not_crash(seeded_db):
    conn = seeded_db
    conn.execute("UPDATE inventory SET qty = 0")
    rng = random.Random(3)
    ensure_work_orders(conn, 3, rng)
    for i in range(5):
        assert step(conn, T0 + timedelta(minutes=i), rng) == 0
    assert _scalar(conn, "SELECT count(*) FROM production_result") == 0


def test_results_never_exceed_planned_and_lots_linked(seeded_db):
    conn = seeded_db
    conn.execute("UPDATE work_order SET planned_qty = planned_qty")  # no-op, 시드엔 작업지시 없음
    rng = random.Random(5)
    ensure_work_orders(conn, 3, rng)
    conn.execute("UPDATE work_order SET planned_qty = 30")  # 빨리 완료되도록 작게
    for i in range(150):
        step(conn, T0 + timedelta(seconds=600 * i), rng, tick_seconds=600)
    over = conn.execute("""
        SELECT wo.wo_id FROM work_order wo JOIN v_wo_progress p USING (wo_id)
        WHERE p.good_qty > wo.planned_qty
    """).fetchall()
    assert over == []
    assert _scalar(conn, "SELECT count(*) FROM work_order WHERE status = 'DONE'") > 0
    assert _scalar(conn, "SELECT count(*) FROM lot_consumption") > 0
    # 모든 실적은 LOT 를 가진다 (FK) 이고 LOT 번호는 고유
    assert _scalar(conn, "SELECT count(*) FROM production_result") == \
        _scalar(conn, "SELECT count(DISTINCT lot_id) FROM production_result")


def test_equipment_logs_stay_non_overlapping(seeded_db):
    conn = seeded_db
    rng = random.Random(11)
    ensure_work_orders(conn, 3, rng)
    for i in range(200):
        step(conn, T0 + timedelta(seconds=300 * i), rng, tick_seconds=300)
    assert _scalar(conn, "SELECT count(*) FROM equipment_status_log WHERE status <> 'RUN'") > 0
    overlaps = conn.execute("""
        SELECT 1 FROM (
            SELECT ended_at, lead(started_at) OVER (PARTITION BY equipment_id ORDER BY started_at, log_id) AS nxt
            FROM equipment_status_log) t
        WHERE nxt IS NOT NULL AND (ended_at IS NULL OR ended_at > nxt)
    """).fetchall()
    assert overlaps == []
    assert _scalar(conn, """SELECT max(c) FROM (SELECT count(*) c FROM equipment_status_log
                            WHERE ended_at IS NULL GROUP BY equipment_id) t""") == 1

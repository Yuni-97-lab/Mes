"""시뮬레이터 테스트: 결정성, 재시작 멱등성, 불량 합계, 재고 고갈, 계획수량, 로그 비중첩,
라인별 작업지시, 일감 없을 때 IDLE(자재대기), 성능률/OEE 현실성, LOT 계보, 시계 규칙, 정지/재시작."""
import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from simulator.simulate import (clock_wait, ensure_work_orders, main, park_equipment, replenish,
                                resume_equipment, resume_point, step)

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 3, 2, 9, 0, tzinfo=KST)  # 주간조, 점심 이전
SHIFTS = [(1, datetime.strptime("08:00", "%H:%M").time(), datetime.strptime("20:00", "%H:%M").time()),
          (2, datetime.strptime("20:00", "%H:%M").time(), datetime.strptime("08:00", "%H:%M").time())]


def _run(conn, seed, steps, tick=60):
    rng = random.Random(seed)
    ensure_work_orders(conn, 3, rng)
    total = 0
    for i in range(steps):
        total += step(conn, T0 + timedelta(seconds=tick * i), rng, tick_seconds=tick)
    return total


def _factory(conn, seed, ticks, dt, start):
    """CLI 루프와 같은 순서(작업지시 보충 → 원자재 보충 → step)로 ticks 틱 진행. 마지막 틱 시각 반환."""
    rng = random.Random(seed)
    sim = start
    for _ in range(ticks):
        ensure_work_orders(conn, 3, rng, now=sim)
        replenish(conn)
        sim += timedelta(seconds=dt)
        step(conn, sim, rng, tick_seconds=dt)
    return sim


def _scalar(conn, sql, params=None):
    return conn.execute(sql, params).fetchone()[0]


def test_step_inserts_results_and_respects_seed(seeded_db):
    conn = seeded_db
    conn.execute("SAVEPOINT s0")
    a = _run(conn, 42, 20)
    conn.execute("ROLLBACK TO SAVEPOINT s0")
    b = _run(conn, 42, 20)
    assert a > 0
    assert a == b


def test_work_orders_cover_every_line_with_sfg_and_fg(seeded_db):
    conn = seeded_db
    rng = random.Random(1)
    # 라인 2개 x (SFG, FG) = 4건. 다시 호출하면 이미 충족되어 0 (재시작 멱등)
    assert ensure_work_orders(conn, 3, rng) == 4
    assert ensure_work_orders(conn, 3, rng) == 0
    rows = conn.execute("""
        SELECT l.name, i.item_type, count(wo.wo_id) FROM line l CROSS JOIN (VALUES ('SFG'), ('FG')) t(tp)
        JOIN item i ON i.item_type = t.tp
        LEFT JOIN work_order wo ON wo.line_id = l.line_id AND wo.item_id = i.item_id
                               AND wo.status IN ('PLANNED','RUNNING')
        GROUP BY l.name, i.item_type ORDER BY 1, 2""").fetchall()
    assert [r[2] for r in rows] == [1, 1, 1, 1]
    # 반제품은 재고+진행 중 계획이 적은 품목부터: 두 라인이 서로 다른 SFG 를 받는다
    assert _scalar(conn, """SELECT count(DISTINCT wo.item_id) FROM work_order wo JOIN item i USING (item_id)
                            WHERE i.item_type = 'SFG'""") == 2


def test_work_orders_use_simulated_time(seeded_db):
    conn = seeded_db
    ensure_work_orders(conn, 3, random.Random(2), now=T0)
    rows = conn.execute("SELECT created_at, due_date FROM work_order").fetchall()
    assert rows and all(c == T0 for c, _ in rows)
    assert all(T0.date() + timedelta(days=2) <= d <= T0.date() + timedelta(days=5) for _, d in rows)


def test_idle_material_wait_when_no_work_then_run_when_work_appears(seeded_db):
    conn = seeded_db
    rng = random.Random(4)
    assert step(conn, T0, rng) == 0           # 작업지시 없음
    rows = conn.execute("""SELECT sl.status, dr.name FROM equipment_status_log sl
                           LEFT JOIN downtime_reason dr USING (reason_id) WHERE sl.ended_at IS NULL""").fetchall()
    assert len(rows) == 12 and set(rows) == {("IDLE", "자재대기")}
    assert _scalar(conn, "SELECT count(*) FROM equipment_status_log WHERE status = 'RUN'") == 0
    ensure_work_orders(conn, 3, rng, now=T0)
    assert step(conn, T0 + timedelta(minutes=10), rng, tick_seconds=600) > 0
    run = {r[0] for r in conn.execute("""SELECT e.name FROM equipment_status_log sl JOIN equipment e
                                         USING (equipment_id) WHERE sl.status = 'RUN'""")}
    assert {"L1-자재투입기", "L2-자재투입기"} <= run


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


@pytest.fixture
def factory_day(seeded_db):
    """주간 시작(08:00)부터 600초 틱으로 25시간: 완전한 교대 2개(주간, 야간)."""
    start = datetime(2026, 3, 2, 8, 0, tzinfo=KST)
    end = _factory(seeded_db, 42, 150, 600, start)
    return seeded_db, start, end


def test_full_shift_oee_and_performance_are_plausible(factory_day):
    conn, start, end = factory_day
    full = "shift_start >= %s AND shift_end <= %s"
    n, oee, perf, avail = conn.execute(
        f"SELECT count(*), avg(oee), avg(performance), avg(availability) FROM v_oee_daily WHERE {full}",
        (start, end)).fetchone()
    assert n == 24   # 설비 12 x 완전한 교대 2
    # 일감 없는 RUN 이 없으므로 성능률은 이상 사이클 대비 실제 속도(75~98%) 범위
    assert 0.75 <= float(perf) <= 1.0
    assert _scalar(conn, f"SELECT max(performance) FROM v_oee_daily WHERE {full}", (start, end)) <= 1.0
    assert 0.6 <= float(avail) <= 0.98
    assert 0.5 <= float(oee) <= 0.8


def test_results_split_at_shift_boundaries(seeded_db):
    conn = seeded_db
    # 틱이 교대 경계(08:00, 20:00)를 걸치도록 07:55 부터 시작: 실적이 교대 창을 넘지 않아야 성능률이 1을 넘지 않는다
    start = datetime(2026, 3, 2, 7, 55, tzinfo=KST)
    end = _factory(conn, 3, 80, 600, start)
    crossing = _scalar(conn, """
        SELECT count(*) FROM production_result pr JOIN shift s USING (shift_id)
        WHERE pr.started_at::time < s.end_time AND pr.ended_at::time > s.end_time
           OR (pr.started_at::time < s.start_time AND pr.ended_at::time > s.start_time
               AND pr.started_at::date = pr.ended_at::date)""")
    assert crossing == 0
    assert _scalar(conn, "SELECT max(performance) FROM v_oee_daily WHERE shift_end <= %s", (end,)) <= 1.0
    # 실적의 교대 = 실적 시작 시각의 교대
    wrong = _scalar(conn, """SELECT count(*) FROM production_result pr JOIN shift s USING (shift_id)
                             WHERE NOT (CASE WHEN s.start_time < s.end_time
                                             THEN pr.started_at::time >= s.start_time AND pr.started_at::time < s.end_time
                                             ELSE pr.started_at::time >= s.start_time OR pr.started_at::time < s.end_time END)""")
    assert wrong == 0


def test_defects_concentrate_at_inspection_processes(factory_day):
    conn, _, _ = factory_day
    rate = dict(conn.execute("SELECT process_code, defect_rate FROM v_defect_rate").fetchall())
    for insp in ("AOI", "FCT"):
        assert all(rate[insp] > rate[p] for p in ("MATIN", "SMT", "ASM", "PACK"))
    avg = _scalar(conn, "SELECT avg(defect_qty / (good_qty + defect_qty)) FROM production_result "
                        "WHERE good_qty + defect_qty > 0")
    assert 0.02 <= float(avg) <= 0.05


def test_lot_genealogy_follows_routing(factory_day):
    conn, _, _ = factory_day
    # 다른 품목(반제품) LOT 를 투입한 간선: 투입 LOT 는 그 품목 라우팅의 마지막 공정(완성 반제품)
    bad_cross = _scalar(conn, """
        SELECT count(*) FROM lot_consumption c
        JOIN lot p ON p.lot_id = c.parent_lot_id JOIN item pi ON pi.item_id = p.item_id
        JOIN lot ch ON ch.lot_id = c.child_lot_id
        WHERE pi.item_type <> 'RM' AND p.item_id <> ch.item_id
          AND p.process_id IS DISTINCT FROM (SELECT r.process_id FROM routing r WHERE r.item_id = p.item_id
                                             ORDER BY r.seq DESC LIMIT 1)""")
    assert bad_cross == 0
    assert _scalar(conn, """SELECT count(*) FROM lot_consumption c JOIN lot p ON p.lot_id = c.parent_lot_id
                            JOIN lot ch ON ch.lot_id = c.child_lot_id JOIN item i ON i.item_id = ch.item_id
                            WHERE i.item_type = 'FG' AND p.item_id <> ch.item_id
                              AND p.wo_id IS NOT NULL""") > 0
    # 같은 품목 간선: 같은 작업지시의 바로 앞 공정 LOT
    bad_same = _scalar(conn, """
        SELECT count(*) FROM lot_consumption c
        JOIN lot p ON p.lot_id = c.parent_lot_id JOIN lot ch ON ch.lot_id = c.child_lot_id
        JOIN routing rp ON rp.item_id = p.item_id AND rp.process_id = p.process_id
        JOIN routing rc ON rc.item_id = ch.item_id AND rc.process_id = ch.process_id
        WHERE p.item_id = ch.item_id AND (p.wo_id <> ch.wo_id OR rp.seq <> rc.seq - 1)""")
    assert bad_same == 0
    # 원자재 LOT: 작업지시 없음, 공급사 LOT 보유, 여러 작업지시가 공유
    assert _scalar(conn, """SELECT count(*) FROM lot l JOIN item i USING (item_id)
                            WHERE i.item_type = 'RM' AND (l.wo_id IS NOT NULL OR l.supplier_lot_no IS NULL)""") == 0
    assert _scalar(conn, """SELECT max(n) FROM (SELECT count(DISTINCT ch.wo_id) n FROM lot_consumption c
                            JOIN lot p ON p.lot_id = c.parent_lot_id JOIN lot ch ON ch.lot_id = c.child_lot_id
                            WHERE p.wo_id IS NULL GROUP BY p.lot_id) t""") > 1
    # 어떤 LOT 도 자기 수량보다 많이 투입되지 않는다
    assert _scalar(conn, """SELECT count(*) FROM (SELECT p.lot_id FROM lot p JOIN lot_consumption c
                            ON c.parent_lot_id = p.lot_id GROUP BY p.lot_id, p.qty
                            HAVING sum(c.qty) > p.qty) t""") == 0


def test_no_run_time_without_work(factory_day):
    conn, _, end = factory_day
    # RUN 구간마다 그 구간과 겹치는 실적이 있어야 한다 (일감 없이 RUN 으로 남지 않음)
    idle_runs = _scalar(conn, """
        SELECT count(*) FROM equipment_status_log sl
        WHERE sl.status = 'RUN' AND COALESCE(sl.ended_at, %s) - sl.started_at > interval '10 minutes'
          AND NOT EXISTS (SELECT 1 FROM production_result pr WHERE pr.equipment_id = sl.equipment_id
                          AND pr.started_at < COALESCE(sl.ended_at, %s) AND pr.ended_at > sl.started_at)""",
        (end, end))
    assert idle_runs == 0


# ---------------------------------------------------------------- 시계 / 정지·재시작
def test_clock_wait_never_lets_sim_pass_wall_clock():
    wall = datetime(2026, 3, 2, 12, 0, tzinfo=KST)
    # 따라잡는 중(목표가 과거): --tick 만큼만 쉬고 바로 진행
    assert clock_wait(wall - timedelta(hours=3), wall, 1.0) == 1.0
    assert clock_wait(wall, wall, 1.0) == 1.0
    # 목표가 미래: 벽시계가 그 시각에 닿을 때까지 기다린다
    assert clock_wait(wall + timedelta(seconds=45), wall, 1.0) == pytest.approx(45)
    for ahead in (0.5, 3, 59, 600):
        target = wall + timedelta(seconds=ahead)
        assert wall + timedelta(seconds=clock_wait(target, wall, 1.0)) >= target


def test_resume_point_rules():
    wall = datetime(2026, 3, 2, 21, 30, tzinfo=KST)
    night = datetime(2026, 3, 2, 20, 0, tzinfo=KST)
    # 빈 DB: --once N 은 마지막 틱이 지금이 되도록 과거부터, 연속 모드는 현재 교대 시작부터
    assert resume_point(None, wall, 600, 300, SHIFTS) == (wall - timedelta(seconds=600 * 300), False)
    assert resume_point(None, wall, 60, None, SHIFTS) == (night, False)
    after_midnight = datetime(2026, 3, 3, 1, 0, tzinfo=KST)
    assert resume_point(None, after_midnight, 60, None, SHIFTS) == (night, False)
    # 최근 데이터가 시작점 이후면 거기서 이어간다 (미래로는 가지 않음)
    last = wall - timedelta(minutes=20)
    assert resume_point(last, wall, 60, None, SHIFTS) == (last, False)
    assert resume_point(wall + timedelta(hours=1), wall, 60, None, SHIFTS) == (wall, False)
    # 오래 멈춰 있었으면 공백: 시작점부터 새로 채우고 공백 표시
    old = wall - timedelta(days=2)
    assert resume_point(old, wall, 60, None, SHIFTS) == (night, True)


def test_park_equipment_leaves_no_open_run(seeded_db):
    conn = seeded_db
    end = _factory(conn, 9, 10, 600, T0)   # 10:40 (점심 시간대 이전)
    assert _scalar(conn, "SELECT count(*) FROM equipment_status_log WHERE ended_at IS NULL AND status='RUN'") > 0
    assert park_equipment(conn, end) > 0
    rows = conn.execute("SELECT status, reason_id, started_at FROM equipment_status_log WHERE ended_at IS NULL"
                        ).fetchall()
    assert len(rows) == 12 and all(r[0] == "IDLE" and r[1] is None and r[2] <= end for r in rows)
    assert _scalar(conn, "SELECT max(ended_at) FROM equipment_status_log") <= end
    assert park_equipment(conn, end) == 0   # 멱등
    # 재개: 정지 로그를 재개 시각에 닫으면 다음 틱에 바로 RUN/자재대기로 시작 (순간정지처럼 복귀를 기다리지 않음)
    conn.execute("SAVEPOINT r")
    resume_equipment(conn, end + timedelta(minutes=30))
    assert _scalar(conn, "SELECT count(*) FROM equipment_status_log WHERE ended_at IS NULL") == 0
    step(conn, end + timedelta(minutes=40), random.Random(1), tick_seconds=600)
    assert _scalar(conn, """SELECT count(DISTINCT equipment_id) FROM equipment_status_log
                            LEFT JOIN downtime_reason USING (reason_id)
                            WHERE started_at = %s AND (status = 'RUN' OR name = '자재대기')""",
                   (end + timedelta(minutes=30),)) == 12
    assert _scalar(conn, "SELECT count(*) FROM equipment_status_log WHERE ended_at IS NULL AND status = 'RUN'") > 0
    conn.execute("ROLLBACK TO SAVEPOINT r")
    # 정지 이후(공백)에는 RUN 시간이 더해지지 않는다: 다음 날 교대 행은 있으나 가동률 0
    later = (end + timedelta(days=1)).date()
    n, avail = conn.execute("SELECT count(*), max(availability) FROM v_oee_daily WHERE work_date = %s",
                            (later,)).fetchone()
    assert n == 24 and avail == 0


def test_cli_once_never_writes_future_and_parks_on_exit(monkeypatch):
    """--once 는 벽시계를 넘지 않고, 종료 시 진행 중 로그를 IDLE 로 정리한다. 재시작은 미래로 가지 않는다."""
    from psycopg.conninfo import make_conninfo

    from mes.db import DEFAULT_URL, connect
    from scripts.init_db import apply_sql, reset_schema
    from tests.conftest import SQL_DIR, TEST_DB

    monkeypatch.setenv("DATABASE_URL",
                       make_conninfo(os.environ.get("DATABASE_URL", DEFAULT_URL), dbname=TEST_DB))
    with connect(TEST_DB) as conn:   # main() 은 별도 연결로 커밋하므로 스키마를 커밋해 둔다
        reset_schema(conn)
        apply_sql(conn, SQL_DIR)
        conn.commit()
    try:
        main(["--once", "6", "--speed", "600", "--seed", "1"])
        with connect(TEST_DB) as conn:
            first = conn.execute("SELECT count(*) FROM production_result").fetchone()[0]
        main(["--once", "6", "--speed", "600", "--seed", "1"])   # 재시작: 지금까지 채워져 있어 진행할 틱 없음
        with connect(TEST_DB) as conn:
            q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
            assert first > 0 and q("SELECT count(*) FROM production_result") == first
            assert q("""SELECT greatest((SELECT max(started_at) FROM equipment_status_log),
                                        (SELECT max(ended_at) FROM equipment_status_log),
                                        (SELECT max(ended_at) FROM production_result),
                                        (SELECT max(created_at) FROM work_order)) <= now()""")
            assert q("SELECT count(*) FROM equipment_status_log WHERE ended_at IS NULL") == 12
            assert q("SELECT count(*) FROM equipment_status_log WHERE ended_at IS NULL "
                     "AND (status <> 'IDLE' OR reason_id IS NOT NULL)") == 0
    finally:
        with connect(TEST_DB) as conn:
            reset_schema(conn)

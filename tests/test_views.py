import pytest


def _wo(conn, item_code, planned_qty):
    return conn.execute(
        "insert into work_order(item_id, line_id, planned_qty)"
        " select i.item_id, l.line_id, %s from item i, line l"
        " where i.item_code = %s and l.name = '라인1' returning wo_id",
        (planned_qty, item_code),
    ).fetchone()[0]


def _result(conn, wo_id, process_code, shift, started_at, good, defect=0, equipment=None):
    """라인1 해당 공정 설비로 실적 1건 INSERT(트리거 통과 조건 충족). result_id 반환."""
    lot_id = conn.execute(
        "insert into lot(lot_no, item_id, wo_id) select 'LOT-' || gen_random_uuid(), item_id, wo_id"
        " from work_order where wo_id = %s returning lot_id",
        (wo_id,),
    ).fetchone()[0]
    return conn.execute(
        "insert into production_result(wo_id, process_id, equipment_id, shift_id, lot_id,"
        " started_at, ended_at, good_qty, defect_qty)"
        " select %s, p.process_id, e.equipment_id, s.shift_id, %s, %s::timestamptz, %s::timestamptz, %s, %s"
        " from process p join equipment e on e.process_id = p.process_id"
        " join line l on l.line_id = e.line_id and l.name = '라인1'"
        " join shift s on s.name = %s where p.code = %s returning result_id",
        (wo_id, lot_id, started_at, started_at, good, defect, shift, process_code),
    ).fetchone()[0]


def _log(conn, equipment_name, status, start, end, reason=None):
    conn.execute(
        "insert into equipment_status_log(equipment_id, status, reason_id, started_at, ended_at)"
        " select e.equipment_id, %s, r.reason_id, %s::timestamptz, %s::timestamptz"
        " from equipment e left join downtime_reason r on r.name = %s where e.name = %s",
        (status, start, end, reason, equipment_name),
    )


def test_oee_fixed_scenario(seeded_db):
    conn = seeded_db
    conn.execute(
        "update routing set ideal_cycle_sec = 60 where item_id ="
        " (select item_id from item where item_code = 'SFG-P01')"
        " and process_id = (select process_id from process where code = 'SMT')"
    )
    wo = _wo(conn, "SFG-P01", 1000)
    _result(conn, wo, "SMT", "주간", "2026-03-10 09:00", good=380, defect=20)
    eq = "L1-SMT-01"
    _log(conn, eq, "RUN", "2026-03-10 08:00", "2026-03-10 11:00")
    _log(conn, eq, "DOWN", "2026-03-10 11:00", "2026-03-10 12:00", "점심")      # 계획 1h
    _log(conn, eq, "RUN", "2026-03-10 12:00", "2026-03-10 17:00")
    _log(conn, eq, "DOWN", "2026-03-10 17:00", "2026-03-10 18:00", "설비고장")  # 비계획 1h
    _log(conn, eq, "RUN", "2026-03-10 18:00", "2026-03-10 20:00")
    row = conn.execute(
        "select availability, performance, quality, oee from v_oee_daily"
        " where equipment_name = %s and shift_name = '주간' and work_date = '2026-03-10'",
        (eq,),
    ).fetchone()
    a, p, q, oee = (float(x) for x in row)
    assert a == pytest.approx(10 / 11, abs=1e-4)
    assert p == pytest.approx(60 * 400 / 36000, abs=1e-4)
    assert q == pytest.approx(0.95, abs=1e-4)
    assert oee == pytest.approx(a * p * q, abs=1e-4)


def test_oee_night_shift_belongs_to_previous_date(seeded_db):
    conn = seeded_db
    wo = _wo(conn, "SFG-P01", 1000)
    _result(conn, wo, "SMT", "야간", "2026-03-11 02:00", good=10)
    rows = conn.execute(
        "select work_date::text from v_oee_daily where equipment_name = 'L1-SMT-01' and shift_name = '야간'"
    ).fetchall()
    assert rows == [("2026-03-10",)]


def test_oee_zero_runtime_is_zero_not_error(seeded_db):
    conn = seeded_db
    wo = _wo(conn, "SFG-P01", 1000)
    # 실적은 있으나 상태 로그가 없는 설비: 행은 나오고 비율은 0, 예외 없음
    _result(conn, wo, "SMT", "주간", "2026-03-10 09:00", good=5, defect=1)
    row = conn.execute(
        "select availability, performance, quality, oee from v_oee_daily where equipment_name = 'L1-SMT-01'"
    ).fetchone()
    assert [float(x) for x in row[:2]] == [0, 0]
    assert float(row[3]) == 0
    assert float(row[2]) == pytest.approx(5 / 6, abs=1e-4)
    # 활동이 전혀 없는 설비는 뷰에 없다
    n = conn.execute("select count(*) from v_oee_daily where equipment_name = 'L2-SMT-01'").fetchone()[0]
    assert n == 0
    # 로그만 있고 실적이 없으면 quality/performance 는 0
    _log(conn, "L2-SMT-01", "RUN", "2026-03-10 08:00", "2026-03-10 10:00")
    row = conn.execute(
        "select availability, performance, quality, oee from v_oee_daily where equipment_name = 'L2-SMT-01'"
    ).fetchone()
    assert float(row[0]) == pytest.approx(2 / 12, abs=1e-4)
    assert [float(x) for x in row[1:]] == [0, 0, 0]


def test_wo_progress_uses_last_process_good_qty(seeded_db):
    conn = seeded_db
    wo = _wo(conn, "SFG-P01", 200)
    _result(conn, wo, "MATIN", "주간", "2026-03-10 09:00", good=100)
    _result(conn, wo, "SMT", "주간", "2026-03-10 10:00", good=90, defect=10)
    _result(conn, wo, "AOI", "주간", "2026-03-10 11:00", good=80)
    row = conn.execute(
        "select item_code, planned_qty, good_qty, progress_pct, status from v_wo_progress where wo_id = %s",
        (wo,),
    ).fetchone()
    assert row[0] == "SFG-P01"
    assert float(row[2]) == 80
    assert float(row[3]) == pytest.approx(40.0, abs=0.05)
    assert row[4] == "RUNNING"


def test_defect_rate_splits_rework_scrap(seeded_db):
    conn = seeded_db
    wo = _wo(conn, "SFG-P01", 200)
    _result(conn, wo, "MATIN", "주간", "2026-03-10 09:00", good=100)
    rid = _result(conn, wo, "SMT", "주간", "2026-03-10 10:00", good=90, defect=10)
    _result(conn, wo, "AOI", "주간", "2026-03-10 11:00", good=80)
    conn.execute(
        "insert into defect_record(result_id, defect_id, kind, qty)"
        " select %s, defect_id, 'rework', 3 from defect_code where name = '납땜불량'", (rid,))
    conn.execute(
        "insert into defect_record(result_id, defect_id, kind, qty)"
        " select %s, defect_id, 'scrap', 7 from defect_code where name = '부품누락'", (rid,))
    row = conn.execute(
        "select input_qty, defect_qty, scrap_qty, rework_qty, defect_rate, fty"
        " from v_defect_rate where process_code = 'SMT'"
    ).fetchone()
    assert [float(x) for x in row[:4]] == [100, 10, 7, 3]
    assert float(row[4]) == pytest.approx(0.1, abs=1e-4)
    assert float(row[5]) == pytest.approx(0.9, abs=1e-4)  # 1.0 * 0.9 * 1.0
    pack = conn.execute("select input_qty, defect_rate from v_defect_rate where process_code = 'PACK'").fetchone()
    assert [float(x) for x in pack] == [0, 0]


def test_equipment_current(seeded_db):
    conn = seeded_db
    _log(conn, "L1-SMT-01", "RUN", "2026-03-10 08:00", "2026-03-10 09:00")
    conn.execute(
        "insert into equipment_status_log(equipment_id, status, started_at)"
        " select equipment_id, 'DOWN', '2026-03-10 09:00'::timestamptz from equipment where name = 'L1-SMT-01'"
    )
    cur = {r[0]: r for r in conn.execute("select name, status, since from v_equipment_current").fetchall()}
    assert len(cur) == 12
    assert cur["L1-SMT-01"][1] == "DOWN"
    assert cur["L2-SMT-01"][1] == "IDLE" and cur["L2-SMT-01"][2] is None


def _avail(conn, equipment, shift, work_date):
    row = conn.execute(
        "select availability from v_oee_daily"
        " where equipment_name = %s and shift_name = %s and work_date = %s",
        (equipment, shift, work_date),
    ).fetchone()
    return None if row is None else float(row[0])


def test_defect_rate_zero_good_does_not_raise(seeded_db):
    conn = seeded_db
    wo = _wo(conn, "SFG-P01", 200)
    _result(conn, wo, "SMT", "주간", "2026-03-10 10:00", good=0, defect=5)
    row = conn.execute(
        "select input_qty, defect_rate, fty from v_defect_rate where process_code = 'SMT'"
    ).fetchone()
    assert [float(x) for x in row] == [5, 1, 0]
    assert conn.execute("select count(*) from v_defect_rate").fetchone()[0] == 6


def test_run_log_spanning_shift_boundary_splits_2h_6h(seeded_db):
    conn = seeded_db
    _log(conn, "L1-AOI-01", "RUN", "2026-03-10 18:00", "2026-03-11 02:00")
    assert _avail(conn, "L1-AOI-01", "주간", "2026-03-10") == pytest.approx(2 / 12, abs=1e-4)
    assert _avail(conn, "L1-AOI-01", "야간", "2026-03-10") == pytest.approx(6 / 12, abs=1e-4)


def test_planned_downtime_straddling_boundary_is_clipped_per_shift(seeded_db):
    conn = seeded_db
    eq = "L1-AOI-01"
    _log(conn, eq, "RUN", "2026-03-10 08:00", "2026-03-10 17:00")                  # 주간 9h
    _log(conn, eq, "DOWN", "2026-03-10 19:00", "2026-03-10 21:00", "정기점검")     # 계획 2h: 주간 1h + 야간 1h
    _log(conn, eq, "RUN", "2026-03-10 21:00", "2026-03-11 05:00")                  # 야간 8h
    assert _avail(conn, eq, "주간", "2026-03-10") == pytest.approx(9 / 11, abs=1e-4)
    assert _avail(conn, eq, "야간", "2026-03-10") == pytest.approx(8 / 11, abs=1e-4)


def test_open_ended_log_is_bounded_by_window_and_now(seeded_db):
    conn = seeded_db
    eq = "L1-AOI-01"
    # 과거에 시작해 아직 진행 중인 로그: 이미 지난 창은 창 길이까지만 계산(=1), 예외 없음
    conn.execute(
        "insert into equipment_status_log(equipment_id, status, started_at)"
        " select equipment_id, 'RUN', '2026-03-10 08:00'::timestamptz from equipment where name = %s", (eq,))
    # 방금 시작한 진행 중 로그(현재 교대 안): now() 를 넘지 않으므로 0~1
    _log(conn, "L2-AOI-01", "RUN", "2026-03-10 08:00", "2026-03-10 09:00")
    conn.execute(
        "insert into equipment_status_log(equipment_id, status, started_at)"
        " select equipment_id, 'RUN', now() - interval '1 hour' from equipment where name = 'L2-SMT-01'")
    assert _avail(conn, eq, "주간", "2026-03-10") == pytest.approx(1.0, abs=1e-6)
    assert _avail(conn, eq, "야간", "2026-03-10") == pytest.approx(1.0, abs=1e-6)
    rows = conn.execute(
        "select availability from v_oee_daily where equipment_name in (%s, 'L2-SMT-01')", (eq,)
    ).fetchall()
    assert rows and all(0 <= float(r[0]) <= 1 for r in rows)

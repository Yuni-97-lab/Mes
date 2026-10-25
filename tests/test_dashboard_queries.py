import pandas as pd
import pytest

from dashboard import queries
from dashboard.messages import EMPTY_MSG
from tests.test_lot_trace import _chain

COLUMNS = {
    "oee_by_equipment": ["equipment_name", "oee", "availability", "performance", "quality"],
    "wo_progress": ["wo_id", "item_code", "planned_qty", "good_qty", "progress_pct",
                    "status", "due_date"],
    "defect_by_process": ["process_code", "input_qty", "defect_qty", "scrap_qty",
                          "rework_qty", "defect_rate", "fty"],
    "equipment_status": ["equipment_id", "name", "status", "since"],
}


@pytest.mark.parametrize("fn", COLUMNS)
def test_queries_return_dataframes_on_empty_db(seeded_db, fn):
    df = getattr(queries, fn)(seeded_db)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == COLUMNS[fn]
    # 시드만 있는 DB 에는 실적이 없다
    if fn == "defect_by_process":
        assert (df["input_qty"] == 0).all()
    elif fn != "equipment_status":
        assert len(df) == 0


def test_numeric_columns_are_float(seeded_db):
    df = queries.defect_by_process(seeded_db)
    assert df["defect_rate"].dtype == float


def test_lot_trace_unknown_lot_is_empty(seeded_db):
    for d, cols in (("forward", ["lot_no", "item_code", "depth"]),
                    ("backward", ["lot_no", "item_code", "supplier_lot_no", "depth"])):
        df = queries.lot_trace(seeded_db, "NOPE", d)
        assert df.empty and list(df.columns) == cols


def test_lot_trace_rejects_bad_direction(seeded_db):
    with pytest.raises(ValueError):
        queries.lot_trace(seeded_db, "RM-A", "sideways")


def test_lot_trace_forward_columns(seeded_db):
    _chain(seeded_db)
    df = queries.lot_trace(seeded_db, "RM-A", "forward")
    assert list(df.columns) == ["lot_no", "item_code", "depth"]
    assert len(df) == 2


def test_lot_trace_backward_columns(seeded_db):
    _chain(seeded_db)
    df = queries.lot_trace(seeded_db, "FG-1", "backward")
    assert list(df.columns) == ["lot_no", "item_code", "supplier_lot_no", "depth"]
    assert len(df) == 2


def test_kpi_summary_on_empty_db(seeded_db):
    k = queries.kpi_summary(seeded_db)
    assert k["avg_oee"] is None and k["defect_rate"] is None
    assert k["running"] == 0 and k["total"] > 0


def _log(conn, equipment_name, status, start, end):
    conn.execute(
        "insert into equipment_status_log(equipment_id, status, started_at, ended_at)"
        " select equipment_id, %s, %s::timestamptz, %s::timestamptz from equipment where name = %s",
        (status, start, end, equipment_name))


def _wo(conn, item_code, qty=1000):
    return conn.execute(
        "insert into work_order(item_id, line_id, planned_qty) select i.item_id, l.line_id, %s"
        " from item i, line l where i.item_code = %s and l.name = '라인1' returning wo_id",
        (qty, item_code)).fetchone()[0]


def _result(conn, wo_id, equipment_name, started_at, good, defect=0):
    lot_id = conn.execute(
        "insert into lot(lot_no, item_id, wo_id) select 'LOT-' || gen_random_uuid(), item_id, wo_id"
        " from work_order where wo_id = %s returning lot_id", (wo_id,)).fetchone()[0]
    conn.execute(
        "insert into production_result(wo_id, process_id, equipment_id, shift_id, lot_id, started_at,"
        " ended_at, good_qty, defect_qty)"
        " select %s, e.process_id, e.equipment_id, s.shift_id, %s, %s::timestamptz, %s::timestamptz, %s, %s"
        " from equipment e, shift s where e.name = %s and s.name = '주간'",
        (wo_id, lot_id, started_at, started_at, good, defect, equipment_name))


def test_oee_by_equipment_ordered_by_line_then_process_seq(seeded_db):
    conn = seeded_db
    for name in ("L2-SMT-01", "L1-AOI-01", "L1-SMT-01", "L1-자재투입기"):
        _log(conn, name, "RUN", "2026-03-10 08:00", "2026-03-10 10:00")
    df = queries.oee_by_equipment(conn)
    assert list(df["equipment_name"]) == ["L1-자재투입기", "L1-SMT-01", "L1-AOI-01", "L2-SMT-01"]


def test_oee_kpi_and_chart_use_latest_two_shifts_only(seeded_db):
    conn = seeded_db
    # 오래된 교대(3/10 주간): 로그만 있어 OEE 0
    _log(conn, "L1-SMT-01", "RUN", "2026-03-10 08:00", "2026-03-10 20:00")
    # 최근 교대(3/12 주간): 12h RUN, SMT 이상 사이클 18초 x 1200개 = 6h -> 성능 0.5, 품질 1
    _log(conn, "L1-SMT-01", "RUN", "2026-03-12 08:00", "2026-03-12 20:00")
    _result(conn, _wo(conn, "SFG-P01", 5000), "L1-SMT-01", "2026-03-12 09:00", good=1200)
    ideal = float(conn.execute(
        "select ideal_cycle_sec from routing join item using (item_id) join process using (process_id)"
        " where item_code = 'SFG-P01' and code = 'SMT'").fetchone()[0])
    expected = ideal * 1200 / (12 * 3600)
    k = queries.kpi_summary(conn)
    assert k["avg_oee"] == pytest.approx(expected, abs=1e-4)
    df = queries.oee_by_equipment(conn)
    assert float(df.loc[df.equipment_name == "L1-SMT-01", "oee"].iloc[0]) == pytest.approx(expected, abs=1e-4)


def test_wo_progress_lists_active_orders_first(seeded_db):
    conn = seeded_db
    done, running, planned = (_wo(conn, "SFG-P01", 10) for _ in range(3))
    conn.execute("update work_order set status = 'DONE' where wo_id = %s", (done,))
    conn.execute("update work_order set status = 'RUNNING' where wo_id = %s", (running,))
    df = queries.wo_progress(conn)
    assert list(df["wo_id"]) == [running, planned, done]


def test_equipment_and_defect_rows_follow_process_seq(seeded_db):
    conn = seeded_db
    seq = [r[0] for r in conn.execute(
        "select e.name from equipment e join process p using (process_id) order by e.line_id, p.seq")]
    assert list(queries.equipment_status(conn)["name"]) == seq
    assert list(queries.defect_by_process(conn)["process_code"]) == ["MATIN", "SMT", "AOI", "ASM", "FCT", "PACK"]


def test_app_shows_info_on_empty_schema(monkeypatch):
    """시드만 있는(실적 없는) mes_test 에서 앱이 예외 없이 안내문을 띄운다."""
    import os
    from pathlib import Path

    from psycopg.conninfo import make_conninfo
    from streamlit.testing.v1 import AppTest

    from mes.db import DEFAULT_URL, connect
    from scripts.init_db import apply_sql, reset_schema
    from tests.conftest import SQL_DIR, TEST_DB

    app = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
    monkeypatch.setenv("DATABASE_URL",
                       make_conninfo(os.environ.get("DATABASE_URL", DEFAULT_URL), dbname=TEST_DB))
    with connect(TEST_DB) as conn:   # 앱은 별도 연결이므로 커밋이 필요하다
        reset_schema(conn)
        apply_sql(conn, SQL_DIR)
        conn.commit()
    try:
        at = AppTest.from_file(str(app), default_timeout=20).run()
        assert not at.exception
        assert [i.value for i in at.info] == [EMPTY_MSG]
    finally:
        with connect(TEST_DB) as conn:
            reset_schema(conn)

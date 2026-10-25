import pandas as pd
import pytest

from dashboard import queries
from tests.test_lot_trace import _chain

COLUMNS = {
    "oee_by_equipment": ["equipment_id", "equipment_name", "shift_name", "work_date",
                         "availability", "performance", "quality", "oee"],
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
        assert [i.value for i in at.info] == [
            "데이터가 없습니다. 시뮬레이터를 실행하세요 (python -m simulator.simulate --speed 60)"]
    finally:
        with connect(TEST_DB) as conn:
            reset_schema(conn)

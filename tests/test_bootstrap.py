from mes.db import connect
from scripts.init_db import apply_sql


def test_connect_returns_pg16():
    with connect() as conn:
        version = conn.execute("show server_version_num").fetchone()[0]
    assert int(version) >= 160000


def test_apply_sql_runs_files_in_order(tmp_path, db):
    (tmp_path / "02_b.sql").write_text("create table b(id int);")
    (tmp_path / "01_a.sql").write_text("create table a(id int);")
    assert apply_sql(db, tmp_path) == ["01_a.sql", "02_b.sql"]
    tables = {
        r[0]
        for r in db.execute(
            "select table_name from information_schema.tables"
            " where table_schema='public'"
        )
    }
    assert {"a", "b"} <= tables


def test_apply_sql_does_not_leak_state(db):
    n = db.execute(
        "select count(*) from information_schema.tables where table_name in ('a','b')"
    ).fetchone()[0]
    assert n == 0

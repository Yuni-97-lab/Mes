from mes.db import connect
from scripts.init_db import apply_sql


def test_connect_returns_pg16():
    with connect() as conn:
        version = conn.execute("show server_version_num").fetchone()[0]
    assert int(version) >= 160000


def test_connect_session_timezone_is_seoul(monkeypatch):
    # 시뮬레이터(KST 교대 배정)와 뷰(세션 TimeZone 기준 교대 창)가 같은 시간대를 쓰도록 고정.
    # 서버/클라이언트 기본값(예: Docker 이미지의 UTC)과 무관해야 하므로 PGTZ 를 UTC 로 두고 확인한다.
    monkeypatch.setenv("PGTZ", "UTC")
    for dbname in (None, "mes_test"):
        with connect(dbname) as conn:
            assert conn.execute("show timezone").fetchone()[0] == "Asia/Seoul"


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

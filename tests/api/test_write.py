from datetime import datetime, timedelta, timezone

import pytest

from backend.app.schemas import ResultIn
from backend.app.services.results import create_result

KST = timezone(timedelta(hours=9), "KST")
TABLES = ("lot", "lot_consumption", "production_result", "defect_record", "inventory_txn")


def _counts(conn):
    return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in TABLES}


def _id(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def _item(conn, code):
    return _id(conn, "select item_id from item where item_code = %s", code)


def _eq(conn, name):
    return _id(conn, "select equipment_id from equipment where name = %s", name)


def _proc(conn, code):
    return _id(conn, "select process_id from process where code = %s", code)


def _wo(client, conn, item="SFG-P01", qty=100, line=1):
    r = client.post("/api/work-orders", json={
        "item_id": _item(conn, item), "line_id": line, "planned_qty": qty, "due_date": "2026-12-31"})
    assert r.status_code == 201, r.text
    return r.json()["wo_id"]


def _post(client, conn, wo, proc, eq, good=10, **extra):
    return client.post("/api/results", json={
        "wo_id": wo, "process_id": _proc(conn, proc), "equipment_id": _eq(conn, eq),
        "good_qty": good, **extra})


def test_create_work_order(client, seeded_db):
    wo = _wo(client, seeded_db, "FG-A100")
    body = client.get(f"/api/work-orders/{wo}").json()
    assert body["status"] == "PLANNED"
    assert body["planned_qty"] == 100


def test_create_work_order_rejects_rm_and_bad_line(client, seeded_db):
    base = {"line_id": 1, "planned_qty": 5, "due_date": "2026-12-31"}
    r = client.post("/api/work-orders", json={**base, "item_id": _item(seeded_db, "RM-PCB")})
    assert r.status_code == 422
    r = client.post("/api/work-orders", json={**base, "item_id": _item(seeded_db, "FG-A100"),
                                              "line_id": 999})
    assert r.status_code == 422
    r = client.post("/api/work-orders", json={**base, "item_id": _item(seeded_db, "FG-A100"),
                                              "planned_qty": 0})
    assert r.status_code == 422


def test_result_creates_lot_lineage_and_txn(client, seeded_db):
    wo = _wo(client, seeded_db)
    r = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기", good=10)
    assert r.status_code == 201, r.text
    assert r.json()["lot_no"] == f"WO-{wo}-MATIN-M1"
    assert _id(seeded_db, "select count(*) from lot where wo_id = %s", wo) == 1
    assert _id(seeded_db, "select count(*) from lot_consumption c join lot l on l.lot_id = c.child_lot_id"
                          " where l.wo_id = %s", wo) >= 1
    assert _id(seeded_db, "select count(*) from production_result where wo_id = %s", wo) == 1
    assert _id(seeded_db, "select count(*) from inventory_txn where ref_result_id = %s",
               r.json()["result_id"]) >= 1
    assert client.get(f"/api/work-orders/{wo}").json()["status"] == "RUNNING"


def test_consecutive_results_increment_lot_suffix(client, seeded_db):
    wo = _wo(client, seeded_db)
    a = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기").json()["lot_no"]
    b = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기").json()["lot_no"]
    assert (a, b) == (f"WO-{wo}-MATIN-M1", f"WO-{wo}-MATIN-M2")


def test_later_process_consumes_previous_process_lot(client, seeded_db):
    wo = _wo(client, seeded_db)
    _post(client, seeded_db, wo, "MATIN", "L1-자재투입기", good=10)
    r = _post(client, seeded_db, wo, "SMT", "L1-SMT-01", good=5, defects=[
        {"defect_id": 1, "kind": "scrap", "qty": 1}])
    assert r.status_code == 201, r.text
    rows = seeded_db.execute(
        "select p.lot_no, c.qty from lot_consumption c join lot p on p.lot_id = c.parent_lot_id"
        " join lot ch on ch.lot_id = c.child_lot_id where ch.lot_no = %s", (r.json()["lot_no"],)).fetchall()
    assert rows == [(f"WO-{wo}-MATIN-M1", 6)]


def test_first_process_of_fg_consumes_sfg_lots(client, seeded_db):
    sfg = _wo(client, seeded_db, "SFG-P01")
    for proc, eq in (("MATIN", "L1-자재투입기"), ("SMT", "L1-SMT-01"), ("AOI", "L1-AOI-01")):
        assert _post(client, seeded_db, sfg, proc, eq, good=10).status_code == 201
    fg = _wo(client, seeded_db, "FG-A100")
    r = _post(client, seeded_db, fg, "ASM", "L1-조립기-01", good=4)
    assert r.status_code == 201, r.text
    parents = [p for (p,) in seeded_db.execute(
        "select p.lot_no from lot_consumption c join lot p on p.lot_id = c.parent_lot_id"
        " join lot ch on ch.lot_id = c.child_lot_id where ch.lot_no = %s", (r.json()["lot_no"],))]
    assert f"WO-{sfg}-AOI-M1" in parents


def test_insufficient_stock_is_409_and_leaves_nothing(client, seeded_db):
    wo = _wo(client, seeded_db)
    seeded_db.execute("update inventory set qty = 0 where item_id in"
                      " (select item_id from item where item_type = 'RM')")
    before = _counts(seeded_db)
    r = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기")
    assert r.status_code == 409
    assert _counts(seeded_db) == before


def _sfg_stock(client, conn, qty):
    """SFG-P01 작업지시를 MATIN→SMT→AOI 로 qty 개 완성해 반제품 재고(와 AOI LOT)를 만든다."""
    sfg = _wo(client, conn, "SFG-P01", qty=qty)
    for proc, eq in (("MATIN", "L1-자재투입기"), ("SMT", "L1-SMT-01"), ("AOI", "L1-AOI-01")):
        assert _post(client, conn, sfg, proc, eq, good=qty).status_code == 201
    return sfg


def test_over_production_is_409_and_leaves_nothing(client, seeded_db):
    # 전공정 재공 검사(422)보다 뒤의 트리거 검사(409)를 보려면 상류 공정을 먼저 정상 입력해 재공을 만든다.
    _sfg_stock(client, seeded_db, 10)
    wo = _wo(client, seeded_db, "FG-A100", qty=5)
    for proc, eq in (("ASM", "L1-조립기-01"), ("FCT", "L1-FCT-01")):
        assert _post(client, seeded_db, wo, proc, eq, good=6).status_code == 201
    before = _counts(seeded_db)
    r = _post(client, seeded_db, wo, "PACK", "L1-포장기-01", good=6)
    assert r.status_code == 409
    assert "초과" in r.json()["detail"]
    assert _counts(seeded_db) == before


def test_later_process_without_upstream_wip_is_422(client, seeded_db):
    wo = _wo(client, seeded_db, "FG-A100", qty=200)
    before = _counts(seeded_db)
    r = _post(client, seeded_db, wo, "PACK", "L1-포장기-01", good=200)
    assert r.status_code == 422
    assert r.json()["detail"] == "전공정 재공이 부족합니다 (가능 수량: 0)"
    assert _counts(seeded_db) == before
    detail = client.get(f"/api/work-orders/{wo}").json()
    assert (detail["status"], detail["good_qty"]) == ("PLANNED", 0)


def test_later_process_input_is_limited_to_upstream_wip(client, seeded_db):
    wo = _wo(client, seeded_db)
    assert _post(client, seeded_db, wo, "MATIN", "L1-자재투입기", good=10).status_code == 201
    before = _counts(seeded_db)
    # 투입 = 양품 8 + 불량 3 = 11 > 전공정 양품 10
    r = _post(client, seeded_db, wo, "SMT", "L1-SMT-01", good=8,
              defects=[{"defect_id": 1, "kind": "scrap", "qty": 3}])
    assert r.status_code == 422
    assert r.json()["detail"] == "전공정 재공이 부족합니다 (가능 수량: 10)"
    assert _counts(seeded_db) == before
    r = _post(client, seeded_db, wo, "SMT", "L1-SMT-01", good=7,
              defects=[{"defect_id": 1, "kind": "scrap", "qty": 3}])
    assert r.status_code == 201, r.text
    parents = seeded_db.execute(
        "select p.lot_no, c.qty from lot_consumption c join lot p on p.lot_id = c.parent_lot_id"
        " join lot ch on ch.lot_id = c.child_lot_id where ch.lot_no = %s", (r.json()["lot_no"],)).fetchall()
    assert parents == [(f"WO-{wo}-MATIN-M1", 10)]
    # 이미 10 을 모두 투입했으므로 남은 재공 0
    r = _post(client, seeded_db, wo, "SMT", "L1-SMT-01", good=1)
    assert r.status_code == 422
    assert r.json()["detail"] == "전공정 재공이 부족합니다 (가능 수량: 0)"
    # AOI 는 SMT 양품(7)까지만
    assert _post(client, seeded_db, wo, "AOI", "L1-AOI-01", good=8).status_code == 422
    assert _post(client, seeded_db, wo, "AOI", "L1-AOI-01", good=7).status_code == 201


def test_later_process_rejects_when_parent_lots_fall_short(client, seeded_db):
    """방어 검사: 실적 수량상 재공은 있어도 전공정 LOT 잔량이 모자라면(데이터 불일치) 422, 아무것도 남기지 않는다."""
    wo = _wo(client, seeded_db)
    r = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기", good=10)
    seeded_db.execute("update lot set qty = 4 where lot_no = %s", (r.json()["lot_no"],))
    before = _counts(seeded_db)
    r = _post(client, seeded_db, wo, "SMT", "L1-SMT-01", good=5)
    assert r.status_code == 422
    assert "전공정 LOT" in r.json()["detail"]
    assert _counts(seeded_db) == before


def test_create_result_locks_work_order_before_lot_numbering(seeded_db, client):
    """수동 LOT 번호(count+1)의 동시 입력 경쟁을 막기 위해 LOT 삽입 전에 작업지시 행을 잠근다."""
    wo = _wo(client, seeded_db)
    seen = []

    class Spy:
        def __getattr__(self, name):
            return getattr(seeded_db, name)

        def execute(self, sql, params=None):
            seen.append(" ".join(str(sql).split()))
            return seeded_db.execute(sql, params)

    payload = ResultIn(wo_id=wo, process_id=_proc(seeded_db, "MATIN"),
                       equipment_id=_eq(seeded_db, "L1-자재투입기"), good_qty=3)
    create_result(Spy(), payload, datetime.now(KST))
    lock = next(i for i, s in enumerate(seen) if "FROM work_order" in s and s.endswith("FOR UPDATE"))
    lot_insert = next(i for i, s in enumerate(seen) if s.startswith("INSERT INTO lot "))
    numbering = next(i for i, s in enumerate(seen) if "FROM lot WHERE lot_no LIKE" in s)
    assert lock < numbering < lot_insert


def test_process_not_in_routing_is_422(client, seeded_db):
    wo = _wo(client, seeded_db, "FG-A100")
    before = _counts(seeded_db)
    r = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기")
    assert r.status_code == 422
    assert _counts(seeded_db) == before


def test_done_work_order_is_422(client, seeded_db):
    wo = _wo(client, seeded_db)
    seeded_db.execute("update work_order set status = 'DONE' where wo_id = %s", (wo,))
    before = _counts(seeded_db)
    assert _post(client, seeded_db, wo, "MATIN", "L1-자재투입기").status_code == 422
    assert _counts(seeded_db) == before


@pytest.mark.parametrize("eq,proc", [("L2-자재투입기", "MATIN"), ("L1-SMT-01", "MATIN")])
def test_equipment_mismatch_is_422(client, seeded_db, eq, proc):
    wo = _wo(client, seeded_db)
    before = _counts(seeded_db)
    assert _post(client, seeded_db, wo, proc, eq).status_code == 422
    assert _counts(seeded_db) == before


@pytest.mark.parametrize("extra", [
    {"good": 0}, {"minutes": 0}, {"minutes": 61}, {"minutes": -1},
    {"defects": [{"defect_id": 9999, "kind": "scrap", "qty": 1}]},
])
def test_invalid_payload_is_422(client, seeded_db, extra):
    wo = _wo(client, seeded_db)
    before = _counts(seeded_db)
    kwargs = {"good": 5, **extra}
    assert _post(client, seeded_db, wo, "MATIN", "L1-자재투입기", **kwargs).status_code == 422
    assert _counts(seeded_db) == before


def test_unknown_wo_and_equipment_are_404(client, seeded_db):
    wo = _wo(client, seeded_db)
    body = {"wo_id": 99999, "process_id": _proc(seeded_db, "MATIN"),
            "equipment_id": _eq(seeded_db, "L1-자재투입기"), "good_qty": 1}
    assert client.post("/api/results", json=body).status_code == 404
    body.update(wo_id=wo, equipment_id=99999)
    assert client.post("/api/results", json=body).status_code == 404


def test_defects_sum(client, seeded_db):
    wo = _wo(client, seeded_db)
    r = _post(client, seeded_db, wo, "MATIN", "L1-자재투입기", good=10, defects=[
        {"defect_id": 1, "kind": "rework", "qty": 1}, {"defect_id": 2, "kind": "scrap", "qty": 2}])
    assert r.status_code == 201, r.text
    row = seeded_db.execute("select defect_qty, rework_qty, started_at, ended_at from production_result"
                            " where result_id = %s", (r.json()["result_id"],)).fetchone()
    assert (row[0], row[1]) == (3, 1)
    assert row[3] - row[2] == timedelta(minutes=1)
    assert _id(seeded_db, "select count(*) from defect_record where result_id = %s",
               r.json()["result_id"]) == 2


@pytest.mark.parametrize("hour,minute,name", [
    (23, 30, "야간"), (2, 0, "야간"), (12, 0, "주간"), (8, 0, "주간"), (20, 0, "야간"), (19, 59, "주간")])
def test_shift_from_local_time(seeded_db, client, hour, minute, name):
    wo = _wo(client, seeded_db)
    now = datetime(2026, 10, 25, hour, minute, tzinfo=KST)
    payload = ResultIn(wo_id=wo, process_id=_proc(seeded_db, "MATIN"),
                       equipment_id=_eq(seeded_db, "L1-자재투입기"), good_qty=3)
    result_id, _ = create_result(seeded_db, payload, now)
    shift = seeded_db.execute("select s.name from production_result r join shift s using (shift_id)"
                              " where r.result_id = %s", (result_id,)).fetchone()[0]
    assert shift == name


def _logs(conn, eq):
    return conn.execute("select status, reason_id, ended_at from equipment_status_log"
                        " where equipment_id = %s order by log_id", (eq,)).fetchall()


def _status(client, eq, status, reason_id=None):
    return client.post(f"/api/equipment/{eq}/status", json={"status": status, "reason_id": reason_id})


def test_status_change_closes_old_and_opens_new(client, seeded_db):
    r = _status(client, 1, "RUN")  # no open log yet
    assert r.status_code == 200 and r.json()["status"] == "RUN"
    reason = _id(seeded_db, "select reason_id from downtime_reason where name = '설비고장'")
    r = _status(client, 1, "DOWN", reason)
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["reason"], body["equipment_id"]) == ("DOWN", "설비고장", 1)
    logs = _logs(seeded_db, 1)
    assert [row[0] for row in logs] == ["RUN", "DOWN"]
    assert logs[0][2] is not None and logs[1][2] is None
    assert body == client.get("/api/equipment").json()[0]


def test_same_status_is_noop(client, seeded_db):
    _status(client, 1, "RUN")
    assert _status(client, 1, "RUN").status_code == 200
    assert len(_logs(seeded_db, 1)) == 1
    lunch = _id(seeded_db, "select reason_id from downtime_reason where name = '점심'")
    _status(client, 1, "IDLE", lunch)
    _status(client, 1, "IDLE", lunch)
    assert len(_logs(seeded_db, 1)) == 2
    _status(client, 1, "IDLE")   # same status, different reason -> new log
    assert len(_logs(seeded_db, 1)) == 3


def test_down_requires_reason_and_unknown_equipment(client, seeded_db):
    assert _status(client, 1, "DOWN").status_code == 422
    assert _status(client, 1, "DOWN", 9999).status_code == 422
    assert _logs(seeded_db, 1) == []
    assert _status(client, 9999, "RUN").status_code == 404
    assert _status(client, 1, "MAINT").status_code == 422


@pytest.mark.parametrize("exc_name", ["UniqueViolation", "DeadlockDetected"])
def test_concurrency_errors_translate_to_409(exc_name):
    import psycopg

    from backend.app.errors import translate_db_error
    err = translate_db_error(getattr(psycopg.errors, exc_name)("conflict"))
    assert err is not None
    assert (err.status_code, err.detail) == (409, "동시에 다른 입력이 처리되었습니다. 다시 시도하세요")


def test_status_change_race_is_409_not_500(seeded_db):
    """열린 로그 조회(FOR UPDATE) 직후 다른 쓰기(시뮬레이터)가 로그를 바꾼 경쟁을 재현:
    조회는 '열린 로그 없음'을 보지만 실제로는 다른 열린 로그가 있어 INSERT 가 유일 인덱스에 걸린다 -> 409."""
    from fastapi.testclient import TestClient

    from backend.app.deps import get_conn
    from backend.app.main import app

    seeded_db.execute("insert into equipment_status_log (equipment_id, status, started_at)"
                      " values (1, 'RUN', now() - interval '1 minute')")
    before = _logs(seeded_db, 1)

    class Racy:
        def __getattr__(self, name):
            return getattr(seeded_db, name)

        def execute(self, sql, params=None):
            if "ended_at IS NULL FOR UPDATE" in sql:
                return seeded_db.execute("SELECT 1 WHERE false")   # 다른 트랜잭션이 막 닫은 것처럼
            return seeded_db.execute(sql, params)

    def _override():
        yield Racy()

    app.dependency_overrides[get_conn] = _override
    try:
        r = TestClient(app, raise_server_exceptions=False).post(
            "/api/equipment/1/status", json={"status": "IDLE", "reason_id": None})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 409, r.text
    assert "다시 시도" in r.json()["detail"]
    assert _logs(seeded_db, 1) == before   # savepoint 롤백: 변경 없음, 트랜잭션도 계속 사용 가능

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


def test_over_production_is_409_and_leaves_nothing(client, seeded_db):
    wo = _wo(client, seeded_db, "FG-A100", qty=100)
    before = _counts(seeded_db)
    r = _post(client, seeded_db, wo, "PACK", "L1-포장기-01", good=101)
    assert r.status_code == 409
    assert "초과" in r.json()["detail"]
    assert _counts(seeded_db) == before


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

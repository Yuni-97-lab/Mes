import pytest


def _lot(conn, lot_no, item_code, supplier=None):
    return conn.execute(
        "insert into lot(lot_no, item_id, supplier_lot_no)"
        " select %s, item_id, %s from item where item_code = %s returning lot_id",
        (lot_no, supplier, item_code),
    ).fetchone()[0]


def _link(conn, parent_id, child_id):
    conn.execute(
        "insert into lot_consumption(parent_lot_id, child_lot_id, qty) values (%s, %s, 1)",
        (parent_id, child_id),
    )


def _make_wo(conn, item_type="FG", line="L1", status="PLANNED"):
    return conn.execute(
        "insert into work_order(item_id, line_id, planned_qty, status)"
        " select i.item_id, l.line_id, 100, %s from item i, line l"
        " where i.item_type = %s and l.line_id = (select min(line_id) from line)"
        " order by i.item_id limit 1 returning wo_id",
        (status, item_type),
    ).fetchone()[0]


@pytest.mark.parametrize("path", [
    "/api/kpi", "/api/oee/equipment", "/api/defects", "/api/equipment",
    "/api/work-orders", "/api/lookups",
])
def test_gets_ok_on_seed_only(client, path):
    assert client.get(path).status_code == 200


def test_kpi(client):
    body = client.get("/api/kpi").json()
    assert body["total_equipment"] == 12
    assert body["avg_oee"] is None
    assert body["running_equipment"] == 0
    assert set(body) == {"avg_oee", "defect_rate", "running_equipment", "total_equipment"}


def test_defects_in_process_order(client):
    rows = client.get("/api/defects").json()
    assert len(rows) == 6
    assert set(rows[0]) == {"process_code", "input_qty", "defect_qty", "scrap_qty",
                            "rework_qty", "defect_rate", "fty"}


def test_equipment_list(client):
    rows = client.get("/api/equipment").json()
    assert len(rows) == 12
    assert all("line_name" in r and "process_seq" in r and "reason" in r for r in rows)
    keys = [(r["line_id"], r["process_seq"]) for r in rows]
    assert keys == sorted(keys)


def test_equipment_detail(client):
    eq = client.get("/api/equipment").json()[0]
    body = client.get(f"/api/equipment/{eq['equipment_id']}").json()
    assert body["name"] == eq["name"]
    assert body["recent_oee"] == []
    assert body["recent_results"] == []
    assert client.get(f"/api/equipment/{eq['equipment_id']}/status-log").json() == []


def test_equipment_not_found(client):
    assert client.get("/api/equipment/9999").status_code == 404


def test_status_log_reason_and_order(client, seeded_db):
    eq = client.get("/api/equipment").json()[0]["equipment_id"]
    seeded_db.execute(
        "insert into equipment_status_log(equipment_id, status, started_at, ended_at)"
        " values (%s, 'RUN', now() - interval '3 hours', now() - interval '2 hours')", (eq,))
    seeded_db.execute(
        "insert into equipment_status_log(equipment_id, status, reason_id, started_at)"
        " select %s, 'DOWN', min(reason_id), now() - interval '2 hours' from downtime_reason",
        (eq,))
    log = client.get(f"/api/equipment/{eq}/status-log?limit=1").json()
    assert len(log) == 1 and log[0]["status"] == "DOWN" and log[0]["reason"]
    row = next(r for r in client.get("/api/equipment").json() if r["equipment_id"] == eq)
    assert row["status"] == "DOWN" and row["reason"]


def test_work_orders_and_detail(client, seeded_db):
    assert client.get("/api/work-orders").json() == []
    done = _make_wo(seeded_db, status="DONE")
    running = _make_wo(seeded_db, status="RUNNING")
    planned = _make_wo(seeded_db)
    ids = [w["wo_id"] for w in client.get("/api/work-orders").json()]
    assert ids == [running, planned, done]
    only = client.get("/api/work-orders?status=DONE").json()
    assert [w["wo_id"] for w in only] == [done]
    assert {"item_name", "line_name", "progress_pct"} <= set(only[0])
    detail = client.get(f"/api/work-orders/{planned}").json()
    assert detail["wo_id"] == planned and detail["lots"] == []
    assert [p["process_code"] for p in detail["processes"]] == ["ASM", "FCT", "PACK"]


def test_work_order_not_found(client):
    assert client.get("/api/work-orders/9999").status_code == 404
    assert client.get("/api/work-orders/9999/options").status_code == 404


def test_lookups(client):
    body = client.get("/api/lookups").json()
    assert len(body["lines"]) == 2
    assert len(body["processes"]) == 6
    seqs = [p["seq"] for p in body["processes"]]
    assert seqs == sorted(seqs)
    assert body["items"] and all(i["item_type"] in ("FG", "SFG") for i in body["items"])
    assert body["reasons"] and "is_planned" in body["reasons"][0]
    assert body["defect_codes"]


def test_options(client, seeded_db):
    wo = _make_wo(seeded_db)
    body = client.get(f"/api/work-orders/{wo}/options").json()
    assert body["wo_id"] == wo and body["status"] == "PLANNED"
    assert [p["code"] for p in body["processes"]] == ["ASM", "FCT", "PACK"]
    line_id = seeded_db.execute("select line_id from work_order where wo_id=%s", (wo,)).fetchone()[0]
    for p in body["processes"]:
        assert len(p["equipment"]) == 1
        got = seeded_db.execute("select line_id from equipment where equipment_id=%s",
                                (p["equipment"][0]["equipment_id"],)).fetchone()[0]
        assert got == line_id


def test_trace(client, seeded_db):
    rm = _lot(seeded_db, "RM-A", "RM-PCB", supplier="SUP-001")
    sfg = _lot(seeded_db, "SFG-1", "SFG-P01")
    fg = _lot(seeded_db, "FG-1", "FG-A100")
    _link(seeded_db, rm, sfg)
    _link(seeded_db, sfg, fg)
    fwd = client.get("/api/lots/RM-A/trace?direction=forward").json()
    assert fwd == [{"lot_no": "SFG-1", "item_code": "SFG-P01", "depth": 1},
                   {"lot_no": "FG-1", "item_code": "FG-A100", "depth": 2}]
    bwd = client.get("/api/lots/FG-1/trace?direction=backward").json()
    assert bwd == [
        {"lot_no": "SFG-1", "item_code": "SFG-P01", "supplier_lot_no": None, "depth": 1},
        {"lot_no": "RM-A", "item_code": "RM-PCB", "supplier_lot_no": "SUP-001", "depth": 2}]


def test_trace_edge_cases(client):
    assert client.get("/api/lots/UNKNOWN/trace?direction=forward").json() == []
    assert client.get("/api/lots/UNKNOWN/trace?direction=backward").json() == []
    assert client.get("/api/lots/X/trace?direction=sideways").status_code == 400

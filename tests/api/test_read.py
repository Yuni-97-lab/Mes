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


# --- 삭제된 Streamlit 쿼리 테스트(tests/test_dashboard_queries.py)에서 이전한, 실제 행이 있는 지표 검증 ---

def _log(conn, equipment_name, status, start, end):
    conn.execute(
        "insert into equipment_status_log(equipment_id, status, started_at, ended_at)"
        " select equipment_id, %s, %s::timestamptz, %s::timestamptz from equipment where name = %s",
        (status, start, end, equipment_name))


def _sfg_wo(conn, qty=5000):
    return conn.execute(
        "insert into work_order(item_id, line_id, planned_qty) select i.item_id, l.line_id, %s"
        " from item i, line l where i.item_code = 'SFG-P01' and l.name = '라인1' returning wo_id",
        (qty,)).fetchone()[0]


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


def test_oee_equipment_ordered_by_line_then_process_seq(client, seeded_db):
    for name in ("L2-SMT-01", "L1-AOI-01", "L1-SMT-01", "L1-자재투입기"):
        _log(seeded_db, name, "RUN", "2026-03-10 08:00", "2026-03-10 10:00")
    rows = client.get("/api/oee/equipment").json()
    assert [r["equipment_name"] for r in rows] == ["L1-자재투입기", "L1-SMT-01", "L1-AOI-01", "L2-SMT-01"]


def test_kpi_oee_and_defects_with_real_rows_are_numeric(client, seeded_db):
    # 오래된 교대(3/10 주간)는 로그만 있어 OEE 0, 최근 교대(3/12 주간)만 집계 대상이어야 한다.
    _log(seeded_db, "L1-SMT-01", "RUN", "2026-03-10 08:00", "2026-03-10 20:00")
    _log(seeded_db, "L1-SMT-01", "RUN", "2026-03-12 08:00", "2026-03-12 20:00")
    # SMT 이상 사이클 x 1200개 / 12h -> 성능률, 불량 30개
    _result(seeded_db, _sfg_wo(seeded_db), "L1-SMT-01", "2026-03-12 09:00", good=1200, defect=30)
    ideal = float(seeded_db.execute(
        "select ideal_cycle_sec from routing join item using (item_id) join process using (process_id)"
        " where item_code = 'SFG-P01' and code = 'SMT'").fetchone()[0])
    expected = ideal * 1230 / (12 * 3600) * (1200 / 1230)

    kpi = client.get("/api/kpi").json()
    assert isinstance(kpi["avg_oee"], float) and kpi["avg_oee"] == pytest.approx(expected, abs=1e-4)
    assert isinstance(kpi["defect_rate"], float) and kpi["defect_rate"] == pytest.approx(30 / 1230, abs=1e-4)

    oee = {r["equipment_name"]: r for r in client.get("/api/oee/equipment").json()}
    smt = oee["L1-SMT-01"]
    assert all(isinstance(smt[k], float) for k in ("oee", "availability", "performance", "quality"))
    assert smt["oee"] == pytest.approx(expected, abs=1e-4)
    assert smt["quality"] == pytest.approx(1200 / 1230, abs=1e-4)

    defects = client.get("/api/defects").json()
    assert [d["process_code"] for d in defects] == ["MATIN", "SMT", "AOI", "ASM", "FCT", "PACK"]
    d = next(d for d in defects if d["process_code"] == "SMT")
    assert d["input_qty"] == 1230 and d["defect_qty"] == 30
    assert isinstance(d["defect_rate"], float) and d["defect_rate"] == pytest.approx(30 / 1230, abs=1e-4)
    assert isinstance(d["fty"], float)

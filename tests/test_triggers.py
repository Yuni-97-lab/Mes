import psycopg
import pytest


def _make_wo(conn, item_code, planned_qty, line="라인1"):
    return conn.execute(
        "insert into work_order(item_id, line_id, planned_qty)"
        " select i.item_id, l.line_id, %s from item i, line l"
        " where i.item_code = %s and l.name = %s returning wo_id",
        (planned_qty, item_code, line),
    ).fetchone()[0]


def _result(conn, wo_id, process_code, good, defect=0):
    """해당 공정의 라인1 설비·주간조로 실적 1건을 INSERT 한다."""
    lot_id = conn.execute(
        "insert into lot(lot_no, item_id, wo_id) select 'LOT-' || gen_random_uuid(), item_id, wo_id"
        " from work_order where wo_id = %s returning lot_id",
        (wo_id,),
    ).fetchone()[0]
    return conn.execute(
        "insert into production_result(wo_id, process_id, equipment_id, shift_id, lot_id,"
        " started_at, ended_at, good_qty, defect_qty)"
        " select %s, p.process_id, e.equipment_id, s.shift_id, %s,"
        " now(), now(), %s, %s"
        " from process p join equipment e on e.process_id = p.process_id"
        " join line l on l.line_id = e.line_id and l.name = '라인1'"
        " join shift s on s.name = '주간' where p.code = %s returning result_id",
        (wo_id, lot_id, good, defect, process_code),
    ).fetchone()[0]


def _inv(conn, item_code):
    return conn.execute(
        "select inv.qty from inventory inv join item i using (item_id) where i.item_code = %s",
        (item_code,),
    ).fetchone()[0]


def _status(conn, wo_id):
    return conn.execute("select status from work_order where wo_id = %s", (wo_id,)).fetchone()[0]


def test_backflush_deducts_rm_and_adds_fg(seeded_db):
    conn = seeded_db
    wo = _make_wo(conn, "SFG-P01", 100)
    before = {c: _inv(conn, c) for c in ("RM-PCB", "RM-IC", "RM-CAP", "RM-RES")}
    rid = _result(conn, wo, "MATIN", good=9, defect=1)  # 투입 10개분
    assert before["RM-PCB"] - _inv(conn, "RM-PCB") == 10
    assert before["RM-IC"] - _inv(conn, "RM-IC") == 20
    assert before["RM-CAP"] - _inv(conn, "RM-CAP") == 100
    assert before["RM-RES"] - _inv(conn, "RM-RES") == 80
    n = conn.execute(
        "select count(*) from inventory_txn where ref_result_id = %s and delta < 0", (rid,)
    ).fetchone()[0]
    assert n == 4
    assert _inv(conn, "SFG-P01") == 0  # 마지막 공정 전에는 증가 없음
    _result(conn, wo, "AOI", good=8)
    assert _inv(conn, "SFG-P01") == 8
    assert conn.execute(
        "select count(*) from inventory_txn t join item i using (item_id)"
        " where i.item_code = 'SFG-P01' and t.delta = 8 and t.ref_result_id is not null"
    ).fetchone()[0] == 1


def test_fg_consumes_sfg_stock(seeded_db):
    conn = seeded_db
    conn.execute("update inventory set qty = 50 where item_id = (select item_id from item where item_code='SFG-P01')")
    wo = _make_wo(conn, "FG-A100", 20)
    _result(conn, wo, "ASM", good=5, defect=0)
    assert _inv(conn, "SFG-P01") == 45


def test_insufficient_stock_rejects_whole_insert(seeded_db):
    conn = seeded_db
    wo = _make_wo(conn, "SFG-P01", 100)
    conn.execute("update inventory set qty = 0 where item_id = (select item_id from item where item_code='RM-IC')")
    before = conn.execute("select count(*) from production_result").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            _result(conn, wo, "MATIN", good=5)
    assert conn.execute("select count(*) from production_result").fetchone()[0] == before
    assert _inv(conn, "RM-PCB") == 1000000  # 부분 차감도 롤백
    assert _status(conn, wo) == "PLANNED"


def test_overproduction_rejected(seeded_db):
    conn = seeded_db
    wo = _make_wo(conn, "SFG-P01", 10)
    with pytest.raises(psycopg.errors.RaiseException, match="work order over-production"):
        with conn.transaction():
            _result(conn, wo, "AOI", good=11)
    # 누적 기준: 6 + 5 > 10
    _result(conn, wo, "AOI", good=6)
    with pytest.raises(psycopg.errors.RaiseException, match="over-production"):
        with conn.transaction():
            _result(conn, wo, "AOI", good=5)
    _result(conn, wo, "AOI", good=4)  # 정확히 10 은 허용


def test_missing_inventory_row_raises_on_consumption(seeded_db):
    conn = seeded_db
    wo = _make_wo(conn, "SFG-P01", 100)
    conn.execute("delete from inventory where item_id = (select item_id from item where item_code='RM-CAP')")
    with pytest.raises(psycopg.errors.RaiseException, match="재고 행이 없습니다"):
        with conn.transaction():
            _result(conn, wo, "MATIN", good=5)
    assert conn.execute("select count(*) from production_result").fetchone()[0] == 0


def test_missing_inventory_row_raises_on_output(seeded_db):
    conn = seeded_db
    wo = _make_wo(conn, "SFG-P01", 100)
    conn.execute("delete from inventory where item_id = (select item_id from item where item_code='SFG-P01')")
    with pytest.raises(psycopg.errors.RaiseException, match="재고 행이 없습니다"):
        with conn.transaction():
            _result(conn, wo, "AOI", good=5)
    assert conn.execute("select count(*) from inventory_txn where ref_result_id is not null").fetchone()[0] == 0


def test_status_transitions_to_running_then_done(seeded_db):
    conn = seeded_db
    wo = _make_wo(conn, "SFG-P01", 10)
    assert _status(conn, wo) == "PLANNED"
    _result(conn, wo, "MATIN", good=10)
    assert _status(conn, wo) == "RUNNING"
    _result(conn, wo, "AOI", good=6)
    assert _status(conn, wo) == "RUNNING"
    _result(conn, wo, "AOI", good=4)
    assert _status(conn, wo) == "DONE"

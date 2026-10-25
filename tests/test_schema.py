import psycopg
import pytest

EXPECTED_TABLES = {
    "item", "bom", "process", "routing", "line", "equipment", "shift",
    "downtime_reason", "defect_code", "work_order", "lot", "lot_consumption",
    "production_result", "defect_record", "equipment_status_log",
    "inventory", "inventory_txn",
}


def test_expected_tables_exist(db):
    rows = db.execute(
        "select table_name from information_schema.tables where table_schema='public'"
    ).fetchall()
    assert EXPECTED_TABLES <= {r[0] for r in rows}


def test_negative_inventory_rejected(db):
    item_id = db.execute(
        "insert into item(item_code, name, item_type, unit)"
        " values ('T-RM', '테스트 원자재', 'RM', 'EA') returning item_id"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        with db.transaction():
            db.execute("insert into inventory(item_id, qty) values (%s, -1)", (item_id,))


def test_seed_counts(seeded_db):
    def one(sql):
        return seeded_db.execute(sql).fetchone()[0]

    assert one("select count(*) from item") == 10
    for t, n in (("FG", 3), ("SFG", 2), ("RM", 5)):
        assert one(f"select count(*) from item where item_type='{t}'") == n
    assert one("select count(*) from equipment") == 12
    assert one("select count(*) from line") == 2
    assert one("select count(*) from process") == 6
    missing = one(
        "select count(*) from item i where i.item_type in ('FG','SFG')"
        " and not exists (select 1 from routing r where r.item_id=i.item_id)"
    )
    assert missing == 0


def test_every_line_has_equipment_for_every_process(seeded_db):
    missing = seeded_db.execute(
        "select count(*) from line l cross join process p"
        " where not exists (select 1 from equipment e"
        " where e.line_id=l.line_id and e.process_id=p.process_id)"
    ).fetchone()[0]
    assert missing == 0


def test_equipment_ids_follow_line_then_process_seq(seeded_db):
    rows = seeded_db.execute(
        "select e.equipment_id, l.name, p.seq from equipment e"
        " join line l using (line_id) join process p using (process_id) order by e.equipment_id"
    ).fetchall()
    assert [(r[1], r[2]) for r in rows] == sorted((r[1], r[2]) for r in rows)


def test_second_open_status_log_rejected(seeded_db):
    conn = seeded_db
    eid = conn.execute("select equipment_id from equipment where name = 'L1-SMT-01'").fetchone()[0]
    ins = "insert into equipment_status_log(equipment_id, status, started_at, ended_at) values (%s, %s, %s, %s)"
    conn.execute(ins, (eid, "RUN", "2026-03-10 08:00+09", "2026-03-10 09:00+09"))   # 닫힌 로그는 여러 개 가능
    conn.execute(ins, (eid, "IDLE", "2026-03-10 09:00+09", None))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            conn.execute(ins, (eid, "RUN", "2026-03-10 10:00+09", None))
    other = conn.execute("select equipment_id from equipment where name = 'L2-SMT-01'").fetchone()[0]
    conn.execute(ins, (other, "RUN", "2026-03-10 10:00+09", None))   # 다른 설비는 별개


def test_non_rm_items_have_zero_inventory_rows(seeded_db):
    n = seeded_db.execute(
        "select count(*) from inventory inv join item i using (item_id)"
        " where i.item_type in ('FG','SFG') and inv.qty = 0"
    ).fetchone()[0]
    assert n == 5

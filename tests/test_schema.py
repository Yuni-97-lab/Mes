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


def test_non_rm_items_have_zero_inventory_rows(seeded_db):
    n = seeded_db.execute(
        "select count(*) from inventory inv join item i using (item_id)"
        " where i.item_type in ('FG','SFG') and inv.qty = 0"
    ).fetchone()[0]
    assert n == 5

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


def _chain(conn):
    rm = _lot(conn, "RM-A", "RM-PCB", supplier="SUP-001")
    sfg = _lot(conn, "SFG-1", "SFG-P01")
    fg = _lot(conn, "FG-1", "FG-A100")
    _link(conn, rm, sfg)
    _link(conn, sfg, fg)


def test_trace_forward(seeded_db):
    _chain(seeded_db)
    rows = seeded_db.execute(
        "select lot_no, item_code, depth from trace_forward('RM-A') order by depth, lot_no"
    ).fetchall()
    assert rows == [("SFG-1", "SFG-P01", 1), ("FG-1", "FG-A100", 2)]


def test_trace_backward(seeded_db):
    _chain(seeded_db)
    rows = seeded_db.execute(
        "select lot_no, item_code, supplier_lot_no, depth from trace_backward('FG-1')"
        " order by depth, lot_no"
    ).fetchall()
    assert rows == [("SFG-1", "SFG-P01", None, 1), ("RM-A", "RM-PCB", "SUP-001", 2)]


def test_unknown_lot_returns_empty(seeded_db):
    assert seeded_db.execute("select * from trace_forward('NOPE')").fetchall() == []
    assert seeded_db.execute("select * from trace_backward('NOPE')").fetchall() == []


def test_cycle_does_not_hang(seeded_db):
    a = _lot(seeded_db, "CYC-A", "SFG-P01")
    b = _lot(seeded_db, "CYC-B", "SFG-P02")
    _link(seeded_db, a, b)
    _link(seeded_db, b, a)
    fwd = seeded_db.execute("select lot_no, depth from trace_forward('CYC-A')").fetchall()
    bwd = seeded_db.execute("select lot_no, depth from trace_backward('CYC-A')").fetchall()
    assert fwd == [("CYC-B", 1)]
    assert bwd == [("CYC-B", 1)]

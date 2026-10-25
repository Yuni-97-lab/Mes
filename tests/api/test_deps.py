"""get_conn 의존성: commit/rollback/close 경로와, 쓰기 응답이 commit 이후에 나가는지."""
import pytest
from fastapi.testclient import TestClient

from backend.app import deps
from backend.app.main import app


class FakeConn:
    def __init__(self, fail_commit=False):
        self.events = []
        self.fail_commit = fail_commit

    def commit(self):
        self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")


def test_get_conn_commits_then_closes_on_success(monkeypatch):
    fake = FakeConn()
    monkeypatch.setattr(deps, "connect", lambda: fake)
    gen = deps.get_conn()
    assert next(gen) is fake
    with pytest.raises(StopIteration):
        next(gen)
    assert fake.events == ["commit", "close"]


def test_get_conn_rolls_back_and_closes_on_error(monkeypatch):
    fake = FakeConn()
    monkeypatch.setattr(deps, "connect", lambda: fake)
    gen = deps.get_conn()
    next(gen)
    with pytest.raises(ValueError):
        gen.throw(ValueError("boom"))
    assert fake.events == ["rollback", "close"]


def test_get_conn_failed_commit_rolls_back_and_closes(monkeypatch):
    fake = FakeConn(fail_commit=True)
    monkeypatch.setattr(deps, "connect", lambda: fake)
    gen = deps.get_conn()
    next(gen)
    with pytest.raises(RuntimeError):
        next(gen)
    assert fake.events == ["commit", "rollback", "close"]


def _proxy(conn, fail_commit):
    """seeded_db 로 쿼리를 위임하되 commit/rollback/close 는 기록만 하는 연결(테스트 트랜잭션 보존)."""
    class Proxy(FakeConn):
        def __getattr__(self, name):
            return getattr(conn, name)

        def execute(self, sql, params=None):
            return conn.execute(sql, params)

        def transaction(self):
            return conn.transaction()

    return Proxy(fail_commit)


@pytest.mark.parametrize("method,url,body", [
    ("post", "/api/work-orders", {"item_id": 1, "line_id": 1, "planned_qty": 5, "due_date": "2026-12-31"}),
    ("post", "/api/equipment/1/status", {"status": "RUN", "reason_id": None}),
])
def test_write_commits_before_response(monkeypatch, seeded_db, method, url, body):
    """실제 get_conn 을 쓰고 commit 을 실패시킨다. commit 이 응답 전에 실행되어야 클라이언트가
    성공(2xx)이 아니라 오류(500)를 받는다. (요청 스코프였다면 2xx 를 받은 뒤 commit 이 실패했다)"""
    fake = _proxy(seeded_db, fail_commit=True)
    monkeypatch.setattr(deps, "connect", lambda: fake)
    r = getattr(TestClient(app, raise_server_exceptions=False), method)(url, json=body)
    assert r.status_code == 500
    assert fake.events == ["commit", "rollback", "close"]


def test_write_success_commits_once_and_closes(monkeypatch, seeded_db):
    fake = _proxy(seeded_db, fail_commit=False)
    monkeypatch.setattr(deps, "connect", lambda: fake)
    r = TestClient(app).post("/api/work-orders", json={
        "item_id": 1, "line_id": 1, "planned_qty": 5, "due_date": "2026-12-31"})
    assert r.status_code == 201
    assert fake.events == ["commit", "close"]

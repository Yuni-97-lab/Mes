import pytest
from fastapi.testclient import TestClient

from backend.app.deps import get_conn
from backend.app.main import app


@pytest.fixture
def client(seeded_db):
    """get_conn 을 seeded_db 연결로 override. commit/close 없이 같은 트랜잭션을 공유한다."""

    def _override():
        yield seeded_db

    app.dependency_overrides[get_conn] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

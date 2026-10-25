import psycopg
from fastapi import HTTPException

from backend.app.errors import translate_db_error


def test_health_returns_ok(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_translate_overproduction_is_409():
    e = translate_db_error(psycopg.errors.RaiseException("work order over-production"))
    assert isinstance(e, HTTPException)
    assert e.status_code == 409
    assert "초과" in e.detail


def test_translate_check_violation_is_409():
    e = translate_db_error(psycopg.errors.CheckViolation("violates check constraint"))
    assert e.status_code == 409
    assert "재고" in e.detail


def test_translate_unknown_returns_none():
    assert translate_db_error(ValueError("x")) is None
    assert translate_db_error(psycopg.errors.RaiseException("other")) is None

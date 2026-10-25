from pathlib import Path

import pytest

from mes.db import connect
from scripts.init_db import apply_sql, reset_schema

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
TEST_DB = "mes_test"


@pytest.fixture(scope="session")
def _test_db_ready():
    """mes_test 를 세션 시작 시 public 스키마 초기화하여 깨끗하게 준비한다."""
    with connect(TEST_DB) as conn:
        reset_schema(conn)
    yield


@pytest.fixture
def db(_test_db_ready):
    """mes_test 연결(비-autocommit). 테스트 종료 시 롤백."""
    conn = connect(TEST_DB)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture(scope="session")
def _seeded_ready(_test_db_ready):
    with connect(TEST_DB) as conn:
        apply_sql(conn, SQL_DIR)
    yield


@pytest.fixture
def seeded_db(_seeded_ready):
    """sql/ 전체(스키마+시드)가 적용된 mes_test 연결. 테스트 후 롤백."""
    conn = connect(TEST_DB)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()

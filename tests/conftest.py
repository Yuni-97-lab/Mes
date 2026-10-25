from pathlib import Path

import pytest

from mes.db import connect
from scripts.init_db import apply_sql, reset_schema

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
TEST_DB = "mes_test"


def _is_schema(name: str) -> bool:
    """이름에 'seed' 가 없는 파일이 스키마 파일이다."""
    return "seed" not in name.lower()


@pytest.fixture(scope="session", autouse=True)
def _clean_test_db():
    """세션 시작 시 mes_test 의 public 스키마를 비워 깨끗하게 만든다."""
    with connect(TEST_DB) as conn:
        reset_schema(conn)


def _open(include):
    """비-autocommit 연결에서 SQL 을 적용한다(DDL 도 트랜잭션 안). 종료 시 롤백하므로 상태가 남지 않는다."""
    conn = connect(TEST_DB)
    try:
        apply_sql(conn, SQL_DIR, include=include)
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def db():
    """스키마만 적용된 mes_test 연결. 테스트 후 롤백."""
    yield from _open(_is_schema)


@pytest.fixture
def seeded_db():
    """스키마 + 시드가 적용된 mes_test 연결. 테스트 후 롤백."""
    yield from _open(None)

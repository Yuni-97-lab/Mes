"""FastAPI 의존성: 요청당 DB 연결."""
from collections.abc import Iterator

import psycopg

from mes.db import connect


def get_conn() -> Iterator[psycopg.Connection]:
    """요청당 연결. 성공 시 commit, 예외 시 rollback, 종료 시 close."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

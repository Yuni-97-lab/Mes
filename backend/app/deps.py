"""FastAPI 의존성: 요청당 DB 연결."""
from collections.abc import Iterator

import psycopg

from mes.db import connect


def get_conn() -> Iterator[psycopg.Connection]:
    """요청당 연결. 성공 시 commit, 예외 시 rollback, 종료 시 close.

    쓰기 엔드포인트는 Depends(get_conn, scope="function") 으로 써서 commit 이 응답 전송 전에 끝나게 한다
    (기본 "request" 스코프는 응답을 보낸 뒤 이 코드를 실행하므로 commit 실패가 사용자에게 보이지 않는다).
    """
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

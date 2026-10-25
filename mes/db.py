"""DB 연결 헬퍼."""
import os

import psycopg
from psycopg.conninfo import make_conninfo

DEFAULT_URL = "postgresql://mes:mes@localhost:5432/mes"
# 교대 창(뷰)과 시뮬레이터의 교대 배정이 같은 시간대를 쓰도록 세션 시간대를 고정한다.
# 서버 기본값(예: Docker postgres 이미지의 UTC)이나 클라이언트 PGTZ 와 무관하게 항상 적용된다.
TIMEZONE = "Asia/Seoul"


def connect(dbname: str | None = None) -> psycopg.Connection:
    """DATABASE_URL(기본값 로컬 mes)로 연결한다. dbname 지정 시 DB 이름만 교체. 세션 시간대는 Asia/Seoul."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    if dbname:
        url = make_conninfo(url, dbname=dbname)
    conn = psycopg.connect(url)
    # 시작 파라미터(PGTZ 등)보다 우선하도록 연결 직후 SET 하고 바로 커밋해 롤백에도 유지되게 한다
    conn.execute("SELECT set_config('TimeZone', %s, false)", (TIMEZONE,))
    conn.commit()
    return conn

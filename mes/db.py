"""DB 연결 헬퍼."""
import os

import psycopg
from psycopg.conninfo import make_conninfo

DEFAULT_URL = "postgresql://mes:mes@localhost:5432/mes"


def connect(dbname: str | None = None) -> psycopg.Connection:
    """DATABASE_URL(기본값 로컬 mes)로 연결한다. dbname 지정 시 DB 이름만 교체."""
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    if dbname:
        url = make_conninfo(url, dbname=dbname)
    return psycopg.connect(url)

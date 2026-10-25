"""스키마/시드 SQL 적용 스크립트. 사용법: python scripts/init_db.py [--reset] [--db NAME]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mes.db import connect  # noqa: E402


def apply_sql(conn, sql_dir: Path = Path("sql"), include=None) -> list[str]:
    """sql_dir 의 *.sql 을 파일명 오름차순으로 실행하고 적용한 파일명을 반환한다.

    include(파일명) -> bool 로 대상을 거를 수 있다. 커밋은 호출자 책임이다.
    """
    applied = []
    for path in sorted(Path(sql_dir).glob("*.sql")):
        if include and not include(path.name):
            continue
        conn.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


def reset_schema(conn) -> None:
    """public 스키마를 DROP/CREATE 하여 초기화한다."""
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="public 스키마 초기화")
    parser.add_argument("--db", help="대상 DB 이름(기본: DATABASE_URL)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    with connect(args.db) as conn:
        if args.reset:
            reset_schema(conn)
        for name in apply_sql(conn, root / "sql"):
            print(f"적용: {name}")
        conn.commit()


if __name__ == "__main__":
    main()

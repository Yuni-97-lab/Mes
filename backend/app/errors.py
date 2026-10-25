"""DB 예외를 HTTP 오류로 변환한다. 라우터에서 `raise translate_db_error(e) or e` 로 사용."""
import psycopg
from fastapi import HTTPException


def translate_db_error(exc: Exception) -> HTTPException | None:
    if isinstance(exc, psycopg.errors.CheckViolation):
        name = getattr(getattr(exc, "diag", None), "constraint_name", None)
        if name is None or "inventory" in name:
            return HTTPException(409, "재고가 부족하여 처리할 수 없습니다")
        return HTTPException(409, f"데이터 제약 조건에 위배되어 처리할 수 없습니다 ({name})")
    if isinstance(exc, psycopg.errors.RaiseException) and "over-production" in str(exc):
        return HTTPException(409, "작업지시 수량을 초과합니다")
    if isinstance(exc, (psycopg.errors.UniqueViolation, psycopg.errors.DeadlockDetected)):
        # 시뮬레이터·다른 사용자와 같은 행(열린 상태 로그, LOT 번호)을 동시에 만들려다 충돌한 경우(교착 포함)
        return HTTPException(409, "동시에 다른 입력이 처리되었습니다. 다시 시도하세요")
    return None

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from backend.app.routers import read, write

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _is_plain_relative(path: str) -> bool:
    """정적 파일 후보가 될 수 있는 평범한 상대 경로인지. 파일시스템을 건드리기 전에 문자열만으로 판정한다.

    '\\'·':'·NUL·선행 '/'·'..' 는 Windows 에서 UNC(\\\\host\\share → SMB 접속)·드라이브 경로·상위 디렉터리·
    잘못된 경로가 될 수 있으므로 거른다 (vite 산출물 이름에는 나오지 않는다).
    """
    if not path or path.startswith("/") or any(ch in path for ch in ("\\", ":", "\x00")):
        return False
    return ".." not in path.split("/")


def create_app(dist_dir: Path | None = None) -> FastAPI:
    """dist_dir(기본 frontend/dist)에 index.html 이 있으면 React 빌드를 함께 서빙한다."""
    app = FastAPI(title="MES API")
    app.include_router(read.router)
    app.include_router(write.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    dist = Path(dist_dir if dist_dir is not None else DEFAULT_DIST).resolve()
    index = dist / "index.html"
    if index.is_file():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "Not Found")   # 없는 API 경로는 index.html 이 아니라 JSON 404
            if _is_plain_relative(path):
                try:
                    target = (dist / path).resolve()
                    if target.is_relative_to(dist) and target.is_file():
                        return FileResponse(target)
                except (OSError, ValueError):
                    pass   # 잘못된 경로는 SPA 라우트로 취급

            if path.startswith("assets/"):
                raise HTTPException(404, "Not Found")   # 없는 정적 자산은 HTML 로 위장하지 않는다
            return FileResponse(index)

    return app


app = create_app()

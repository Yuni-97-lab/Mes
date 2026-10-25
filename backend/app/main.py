from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from backend.app.routers import read, write

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


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
            target = (dist / path).resolve()
            if path and target.is_file() and target.is_relative_to(dist):
                return FileResponse(target)
            if path.startswith("assets/"):
                raise HTTPException(404, "Not Found")   # 없는 정적 자산은 HTML 로 위장하지 않는다
            return FileResponse(index)

    return app


app = create_app()

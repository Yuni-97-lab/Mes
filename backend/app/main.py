from fastapi import FastAPI

from backend.app.routers import read

app = FastAPI(title="MES API")
app.include_router(read.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}

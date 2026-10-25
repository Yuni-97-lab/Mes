from fastapi import FastAPI

from backend.app.routers import read, write

app = FastAPI(title="MES API")
app.include_router(read.router)
app.include_router(write.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}

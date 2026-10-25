from fastapi import FastAPI

app = FastAPI(title="MES API")


@app.get("/api/health")
def health():
    return {"status": "ok"}

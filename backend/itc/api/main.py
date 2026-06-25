from fastapi import FastAPI

app = FastAPI(title="ITC Recovery API")


@app.get("/health")
async def health():
    return {"status": "ok"}
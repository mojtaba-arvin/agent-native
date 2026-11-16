from fastapi import FastAPI

app = FastAPI(title="orders-service", version="0.1.0")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}


@app.get("/orders", tags=["orders"])
async def list_orders():
    return {"items": []}

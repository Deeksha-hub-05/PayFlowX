from fastapi import FastAPI

app = FastAPI(
    title="PayFlowX",
    version="0.1.0",
    description="Intelligent Payment Orchestration Engine",
)


@app.get("/api/v1/health", tags=["Operations"])
async def health():
    return {
        "status": "ok",
        "service": "PayFlowX",
    }

from fastapi import FastAPI

from app.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Intelligent Payment Orchestration Engine",
)


@app.get("/api/v1/health", tags=["Operations"])
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }

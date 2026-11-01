
from fastapi import FastAPI

from app.config import settings

from app.api.payments import router as payments_router
from app.api.webhooks import router as webhooks_router
from app.api.refunds import router as refunds_router
from app.api.gateways import router as gateways_router
from app.api.gateway_health import router as gateway_health_router
from app.api.reconciliation import router as reconciliation_router


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Intelligent Payment Orchestration Engine",
)

app.include_router(payments_router)
app.include_router(webhooks_router)
app.include_router(refunds_router)
app.include_router(gateways_router)
app.include_router(gateway_health_router)
app.include_router(reconciliation_router)


@app.get("/api/v1/health", tags=["Operations"])
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }

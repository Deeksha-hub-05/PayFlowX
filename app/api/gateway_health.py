
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.gateway_health_metric import GatewayHealthMetric
from app.models.gateway_circuit_breaker import GatewayCircuitBreaker


router = APIRouter(
    prefix="/api/v1/gateway-health",
    tags=["Gateway Health"],
)


class GatewayHealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: object
    gateway_name: str
    payment_method: str
    success_count: int
    failure_count: int
    average_latency_ms: float
    is_healthy: bool
    measured_at: datetime


class CircuitBreakerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: object
    gateway_name: str
    payment_method: str
    state: str
    failure_count: int
    failure_threshold: int
    recovery_timeout_seconds: int
    last_failure_at: Optional[datetime]
    opened_at: Optional[datetime]
    updated_at: datetime


class CircuitBreakerResetResponse(BaseModel):
    message: str
    gateway_name: str
    payment_method: str
    state: str


# 1. View gateway health metrics

@router.get("/metrics", response_model=list[GatewayHealthResponse])
async def list_gateway_health_metrics(
    gateway_name: Optional[str] = None,
    payment_method: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(GatewayHealthMetric)

    if gateway_name:
        query = query.where(
            GatewayHealthMetric.gateway_name == gateway_name
        )

    if payment_method:
        query = query.where(
            GatewayHealthMetric.payment_method == payment_method
        )

    query = query.order_by(
        GatewayHealthMetric.measured_at.desc()
    ).limit(limit)

    result = await db.execute(query)

    return result.scalars().all()


# 2. View circuit breaker states

@router.get("/circuit-breakers", response_model=list[CircuitBreakerResponse])
async def list_circuit_breakers(
    gateway_name: Optional[str] = None,
    payment_method: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(GatewayCircuitBreaker)

    if gateway_name:
        query = query.where(
            GatewayCircuitBreaker.gateway_name == gateway_name
        )

    if payment_method:
        query = query.where(
            GatewayCircuitBreaker.payment_method == payment_method
        )

    result = await db.execute(
        query.order_by(GatewayCircuitBreaker.gateway_name)
    )

    return result.scalars().all()


# 3. Reset a circuit breaker

@router.post(
    "/circuit-breakers/{gateway_name}/{payment_method}/reset",
    response_model=CircuitBreakerResetResponse,
)
async def reset_circuit_breaker(
    gateway_name: str,
    payment_method: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GatewayCircuitBreaker).where(
            GatewayCircuitBreaker.gateway_name == gateway_name,
            GatewayCircuitBreaker.payment_method == payment_method,
        )
    )

    breaker = result.scalar_one_or_none()

    if breaker is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circuit breaker not found",
        )

    breaker.state = "CLOSED"
    breaker.failure_count = 0
    breaker.last_failure_at = None
    breaker.opened_at = None

    await db.commit()
    await db.refresh(breaker)

    return CircuitBreakerResetResponse(
        message="Circuit breaker reset successfully",
        gateway_name=gateway_name,
        payment_method=payment_method,
        state=breaker.state,
    )


from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.gateway_config import GatewayConfig


router = APIRouter(
    prefix="/api/v1/gateways",
    tags=["Gateway Management"],
)


# -----------------------------
# Request schemas
# -----------------------------

class GatewayConfigCreate(BaseModel):
    gateway_name: str = Field(min_length=2, max_length=50)
    is_enabled: bool = True
    timeout_ms: int = Field(default=2000, ge=100, le=30000)
    max_retries: int = Field(default=2, ge=0, le=10)
    cost_per_transaction: float = Field(default=0.0, ge=0)


class GatewayConfigUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    timeout_ms: Optional[int] = Field(default=None, ge=100, le=30000)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    cost_per_transaction: Optional[float] = Field(default=None, ge=0)


# -----------------------------
# Response schema
# -----------------------------

class GatewayConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gateway_name: str
    is_enabled: bool
    timeout_ms: int
    max_retries: int
    cost_per_transaction: float
    created_at: datetime
    updated_at: datetime


# -----------------------------
# Helper
# -----------------------------

async def get_gateway(
    gateway_name: str,
    db: AsyncSession,
) -> GatewayConfig:
    result = await db.execute(
        select(GatewayConfig).where(
            GatewayConfig.gateway_name == gateway_name
        )
    )

    gateway = result.scalar_one_or_none()

    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gateway not found",
        )

    return gateway


# -----------------------------
# 1. List all gateways
# -----------------------------

@router.get(
    "",
    response_model=list[GatewayConfigResponse],
)
async def list_gateways(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GatewayConfig).order_by(
            GatewayConfig.gateway_name
        )
    )

    return result.scalars().all()


# -----------------------------
# 2. Get gateway details
# -----------------------------

@router.get(
    "/{gateway_name}",
    response_model=GatewayConfigResponse,
)
async def get_gateway_details(
    gateway_name: str,
    db: AsyncSession = Depends(get_db),
):
    return await get_gateway(gateway_name, db)


# -----------------------------
# 3. Register a new gateway
# -----------------------------

@router.post(
    "",
    response_model=GatewayConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gateway(
    payload: GatewayConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(GatewayConfig).where(
            GatewayConfig.gateway_name == payload.gateway_name
        )
    )

    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gateway already exists",
        )

    gateway = GatewayConfig(
        gateway_name=payload.gateway_name,
        is_enabled=payload.is_enabled,
        timeout_ms=payload.timeout_ms,
        max_retries=payload.max_retries,
        cost_per_transaction=payload.cost_per_transaction,
    )

    db.add(gateway)

    try:
        await db.commit()
        await db.refresh(gateway)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gateway already exists",
        )

    return gateway


# -----------------------------
# 4. Update gateway configuration
# -----------------------------

@router.put(
    "/{gateway_name}",
    response_model=GatewayConfigResponse,
)
async def update_gateway(
    gateway_name: str,
    payload: GatewayConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    gateway = await get_gateway(gateway_name, db)

    updates = payload.model_dump(exclude_unset=True)

    for field, value in updates.items():
        setattr(gateway, field, value)

    try:
        await db.commit()
        await db.refresh(gateway)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gateway configuration update failed",
        )

    return gateway


# -----------------------------
# 5. Enable gateway
# -----------------------------

@router.patch(
    "/{gateway_name}/enable",
    response_model=GatewayConfigResponse,
)
async def enable_gateway(
    gateway_name: str,
    db: AsyncSession = Depends(get_db),
):
    gateway = await get_gateway(gateway_name, db)

    gateway.is_enabled = True

    await db.commit()
    await db.refresh(gateway)

    return gateway


# -----------------------------
# 6. Disable gateway
# -----------------------------

@router.patch(
    "/{gateway_name}/disable",
    response_model=GatewayConfigResponse,
)
async def disable_gateway(
    gateway_name: str,
    db: AsyncSession = Depends(get_db),
):
    gateway = await get_gateway(gateway_name, db)

    gateway.is_enabled = False

    await db.commit()
    await db.refresh(gateway)

    return gateway

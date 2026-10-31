
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_circuit_breaker import GatewayCircuitBreaker


CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


async def get_or_create_breaker(
    db: AsyncSession,
    gateway_name: str,
    payment_method: str,
) -> GatewayCircuitBreaker:
    result = await db.execute(
        select(GatewayCircuitBreaker)
        .where(
            GatewayCircuitBreaker.gateway_name == gateway_name,
            GatewayCircuitBreaker.payment_method == payment_method,
        )
        .with_for_update()
    )

    breaker = result.scalar_one_or_none()

    if breaker is None:
        breaker = GatewayCircuitBreaker(
            gateway_name=gateway_name,
            payment_method=payment_method,
        )
        db.add(breaker)
        await db.flush()

    return breaker


async def is_gateway_available(
    db: AsyncSession,
    gateway_name: str,
    payment_method: str,
) -> bool:
    breaker = await get_or_create_breaker(
        db, gateway_name, payment_method
    )

    if breaker.state == CLOSED:
        return True

    if breaker.state == OPEN:
        if breaker.opened_at is None:
            return False

        recovery_time = breaker.opened_at + timedelta(
            seconds=breaker.recovery_timeout_seconds
        )

        if datetime.now(timezone.utc) >= recovery_time:
            breaker.state = HALF_OPEN
            breaker.updated_at = datetime.now(timezone.utc)
            await db.flush()
            return True

        return False

    return False


async def record_gateway_success(
    db: AsyncSession,
    gateway_name: str,
    payment_method: str,
) -> None:
    breaker = await get_or_create_breaker(
        db, gateway_name, payment_method
    )

    breaker.state = CLOSED
    breaker.failure_count = 0
    breaker.last_failure_at = None
    breaker.opened_at = None
    breaker.updated_at = datetime.now(timezone.utc)

    await db.flush()


async def record_gateway_failure(
    db: AsyncSession,
    gateway_name: str,
    payment_method: str,
) -> None:
    breaker = await get_or_create_breaker(
        db, gateway_name, payment_method
    )

    now = datetime.now(timezone.utc)

    breaker.failure_count += 1
    breaker.last_failure_at = now

    if breaker.failure_count >= breaker.failure_threshold:
        breaker.state = OPEN
        breaker.opened_at = now

    breaker.updated_at = now

    await db.flush()


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_route import GatewayRoute


async def select_gateway(
    db: AsyncSession,
    payment_method: str,
) -> GatewayRoute | None:
    """Select the highest-priority enabled gateway for a payment method."""
    result = await db.execute(
        select(GatewayRoute)
        .where(
            GatewayRoute.payment_method == payment_method,
            GatewayRoute.is_enabled.is_(True),
        )
        .order_by(
            GatewayRoute.priority.asc(),
            GatewayRoute.id.asc(),
        )
        .limit(1)
    )

    return result.scalar_one_or_none()

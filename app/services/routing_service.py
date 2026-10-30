from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_health_metric import GatewayHealthMetric
from app.models.gateway_route import GatewayRoute


def calculate_gateway_score(
    route: GatewayRoute,
    health: GatewayHealthMetric,
    min_latency: float,
    max_latency: float,
    min_cost: float,
    max_cost: float,
) -> float:
    """Calculate a weighted routing score between 0 and 100."""

    total_requests = health.success_count + health.failure_count

    success_rate = (
        health.success_count / total_requests
        if total_requests > 0
        else 0.0
    )

    if max_latency == min_latency:
        latency_score = 100.0
    else:
        latency_score = (
            (max_latency - health.average_latency_ms)
            / (max_latency - min_latency)
        ) * 100

    if max_cost == min_cost:
        cost_score = 100.0
    else:
        cost_score = (
            (max_cost - route.cost_per_transaction)
            / (max_cost - min_cost)
        ) * 100

    health_score = 100.0 if health.is_healthy else 0.0

    payment_method_score = 100.0

    return (
        success_rate * 100 * 0.35
        + latency_score * 0.20
        + cost_score * 0.20
        + health_score * 0.15
        + payment_method_score * 0.10
    )


async def select_gateway(
    db: AsyncSession,
    payment_method: str,
) -> GatewayRoute | None:
    """Select the highest-scoring healthy gateway for a payment method."""

    routes_result = await db.execute(
        select(GatewayRoute).where(
            GatewayRoute.payment_method == payment_method,
            GatewayRoute.is_enabled.is_(True),
        )
    )
    routes = routes_result.scalars().all()

    if not routes:
        return None

    health_result = await db.execute(
        select(GatewayHealthMetric).where(
            GatewayHealthMetric.payment_method == payment_method,
            GatewayHealthMetric.is_healthy.is_(True),
        )
    )
    health_metrics = health_result.scalars().all()

    health_by_gateway = {
        metric.gateway_name: metric
        for metric in health_metrics
    }

    eligible = [
        (route, health_by_gateway[route.gateway_name])
        for route in routes
        if route.gateway_name in health_by_gateway
    ]

    if not eligible:
        return None

    latencies = [
        health.average_latency_ms
        for _, health in eligible
    ]
    costs = [
        route.cost_per_transaction
        for route, _ in eligible
    ]

    min_latency = min(latencies)
    max_latency = max(latencies)
    min_cost = min(costs)
    max_cost = max(costs)

    scored_routes = [
        (
            calculate_gateway_score(
                route,
                health,
                min_latency,
                max_latency,
                min_cost,
                max_cost,
            ),
            route,
        )
        for route, health in eligible
    ]

    scored_routes.sort(
        key=lambda item: (
            -item[0],
            item[1].priority,
            item[1].id,
        )
    )

    return scored_routes[0][1]
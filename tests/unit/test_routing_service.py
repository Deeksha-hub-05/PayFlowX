from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.gateway_health_metric import GatewayHealthMetric
from app.models.gateway_route import GatewayRoute
from app.services.routing_service import (
    calculate_gateway_score,
    select_gateway,
)


def make_route(
    gateway_name: str,
    priority: int = 100,
    cost: float = 1.0,
    route_id: int = 1,
) -> GatewayRoute:
    return GatewayRoute(
        id=route_id,
        gateway_name=gateway_name,
        payment_method="UPI",
        priority=priority,
        cost_per_transaction=cost,
        is_enabled=True,
    )


def make_health(
    gateway_name: str,
    success: int = 90,
    failure: int = 10,
    latency: float = 100.0,
    healthy: bool = True,
) -> GatewayHealthMetric:
    return GatewayHealthMetric(
        gateway_name=gateway_name,
        payment_method="UPI",
        success_count=success,
        failure_count=failure,
        average_latency_ms=latency,
        is_healthy=healthy,
    )


def mock_db_results(db, routes, metrics):
    routes_result = MagicMock()
    routes_result.scalars.return_value.all.return_value = routes

    metrics_result = MagicMock()
    metrics_result.scalars.return_value.all.return_value = metrics

    db.execute = AsyncMock(
        side_effect=[routes_result, metrics_result]
    )


@pytest.mark.asyncio
async def test_select_gateway_returns_highest_scoring_gateway():
    razorpay = make_route("razorpay", cost=2.0, route_id=1)
    stripe = make_route("stripe", cost=1.0, route_id=2)

    razorpay_health = make_health(
        "razorpay", success=70, latency=200
    )
    stripe_health = make_health(
        "stripe", success=98, latency=50
    )

    db = AsyncMock()
    mock_db_results(
        db,
        [razorpay, stripe],
        [razorpay_health, stripe_health],
    )

    selected = await select_gateway(db, "UPI")

    assert selected is stripe
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_select_gateway_returns_none_when_no_routes_match():
    db = AsyncMock()
    mock_db_results(db, [], [])

    selected = await select_gateway(db, "UPI")

    assert selected is None


@pytest.mark.asyncio
async def test_select_gateway_excludes_unhealthy_gateways():
    unhealthy_route = make_route("razorpay", route_id=1)
    healthy_route = make_route("stripe", route_id=2)

    unhealthy_health = make_health(
        "razorpay", healthy=False
    )
    healthy_health = make_health("stripe")

    db = AsyncMock()
    mock_db_results(
        db,
        [unhealthy_route, healthy_route],
        [healthy_health],
    )

    selected = await select_gateway(db, "UPI")

    assert selected is healthy_route


@pytest.mark.asyncio
async def test_select_gateway_returns_none_without_health_metrics():
    route = make_route("razorpay")

    db = AsyncMock()
    mock_db_results(db, [route], [])

    selected = await select_gateway(db, "UPI")

    assert selected is None


def test_gateway_score_rewards_higher_success_rate():
    route = make_route("razorpay")
    excellent = make_health(
        "razorpay", success=99, failure=1
    )
    poor = make_health(
        "razorpay", success=50, failure=50
    )

    excellent_score = calculate_gateway_score(
        route, excellent, 100, 100, 1, 1
    )
    poor_score = calculate_gateway_score(
        route, poor, 100, 100, 1, 1
    )

    assert excellent_score > poor_score


def test_gateway_score_rewards_lower_cost():
    route = make_route("razorpay", cost=1.0)
    health = make_health("razorpay")

    low_cost_score = calculate_gateway_score(
        route, health, 100, 100, 1, 5
    )

    expensive_route = make_route(
        "razorpay", cost=5.0
    )
    high_cost_score = calculate_gateway_score(
        expensive_route, health, 100, 100, 1, 5
    )

    assert low_cost_score > high_cost_score


def test_gateway_score_rewards_lower_latency():
    route = make_route("razorpay")
    health = make_health("razorpay", latency=50)

    fast_score = calculate_gateway_score(
        route, health, 50, 200, 1, 1
    )

    slow_health = make_health(
        "razorpay", latency=200
    )
    slow_score = calculate_gateway_score(
        route, slow_health, 50, 200, 1, 1
    )

    assert fast_score > slow_score
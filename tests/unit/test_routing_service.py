
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.gateway_route import GatewayRoute
from app.services.routing_service import select_gateway


@pytest.mark.asyncio
async def test_select_gateway_returns_highest_priority_enabled_route():
    expected_route = GatewayRoute(
        id=1,
        gateway_name="razorpay",
        payment_method="UPI",
        priority=1,
        is_enabled=True,
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = expected_route

    db = AsyncMock()
    db.execute.return_value = result

    selected = await select_gateway(db, "UPI")

    assert selected is expected_route
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_select_gateway_returns_none_when_no_route_matches():
    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.execute.return_value = result

    selected = await select_gateway(db, "UPI")

    assert selected is None
    db.execute.assert_awaited_once()


import pytest

from app.gateways.mock_gateway import MockGateway


@pytest.mark.asyncio
async def test_mock_gateway_success():
    gateway = MockGateway("razorpay")

    result = await gateway.charge(
        amount=10000,
        payment_method="UPI",
        outcome="success",
        delay_ms=0,
    )

    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert result.gateway_name == "razorpay"


@pytest.mark.asyncio
async def test_mock_gateway_decline():
    gateway = MockGateway("stripe")

    result = await gateway.charge(
        amount=10000,
        payment_method="CARD",
        outcome="failure",
        delay_ms=0,
    )

    assert result.success is False
    assert result.status == "FAILED"


@pytest.mark.asyncio
async def test_mock_gateway_timeout_is_unknown():
    gateway = MockGateway("payu")

    result = await gateway.charge(
        amount=10000,
        payment_method="UPI",
        outcome="timeout",
        delay_ms=0,
    )

    assert result.success is False
    assert result.status == "UNKNOWN"


@pytest.mark.asyncio
async def test_mock_gateway_down_returns_immediately():
    gateway = MockGateway("razorpay")

    result = await gateway.charge(
        amount=10000,
        payment_method="UPI",
        gateway_down=True,
    )

    assert result.success is False
    assert result.status == "GATEWAY_DOWN"
    assert result.latency_ms == 0


@pytest.mark.asyncio
async def test_mock_gateway_rejects_invalid_amount():
    gateway = MockGateway("razorpay")

    with pytest.raises(ValueError, match="Amount must be greater than zero"):
        await gateway.charge(
            amount=0,
            payment_method="UPI",
        )


@pytest.mark.asyncio
async def test_mock_gateway_rejects_negative_delay():
    gateway = MockGateway("razorpay")

    with pytest.raises(ValueError, match="Delay cannot be negative"):
        await gateway.charge(
            amount=10000,
            payment_method="UPI",
            delay_ms=-1,
        )

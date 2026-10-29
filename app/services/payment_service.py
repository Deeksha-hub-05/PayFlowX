
from app.gateways.mock_gateway import GatewayResult, MockGateway


async def process_mock_payment(
    gateway_name: str,
    amount: int,
    payment_method: str,
    outcome: str = "success",
    delay_ms: int = 50,
    gateway_down: bool = False,
) -> GatewayResult:
    """Execute a payment using the selected mock gateway."""
    gateway = MockGateway(gateway_name)

    return await gateway.charge(
        amount=amount,
        payment_method=payment_method,
        outcome=outcome,  # type: ignore[arg-type]
        delay_ms=delay_ms,
        gateway_down=gateway_down,
    )


import asyncio
from dataclasses import dataclass
from typing import Literal


MockOutcome = Literal["success", "failure", "timeout", "error"]


@dataclass(frozen=True)
class GatewayResult:
    gateway_name: str
    success: bool
    status: str
    message: str
    latency_ms: int


class MockGateway:
    """Simulate a payment gateway without external network access."""

    def __init__(self, gateway_name: str):
        self.gateway_name = gateway_name

    async def charge(
        self,
        amount: int,
        payment_method: str,
        outcome: MockOutcome = "success",
        delay_ms: int = 50,
        gateway_down: bool = False,
    ) -> GatewayResult:
        """Simulate a charge and return a predictable gateway result."""

        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")

        if delay_ms < 0:
            raise ValueError("Delay cannot be negative.")

        if gateway_down:
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="GATEWAY_DOWN",
                message="Mock gateway is unavailable.",
                latency_ms=0,
            )

        await asyncio.sleep(delay_ms / 1000)

        if outcome == "success":
            success = True
            status = "SUCCEEDED"
            message = "Mock payment succeeded."
        elif outcome == "failure":
            success = False
            status = "FAILED"
            message = "Mock payment was declined."
        elif outcome == "timeout":
            success = False
            status = "UNKNOWN"
            message = "Mock gateway timed out; payment outcome is unknown."
        elif outcome == "error":
            success = False
            status = "ERROR"
            message = "Mock gateway returned an internal error."
        else:
            raise ValueError(f"Unsupported mock outcome: {outcome}")

        return GatewayResult(
            gateway_name=self.gateway_name,
            success=success,
            status=status,
            message=message,
            latency_ms=delay_ms,
        )

    async def refund(
        self,
        amount: int,
        outcome: MockOutcome = "success",
        delay_ms: int = 50,
        gateway_down: bool = False,
    ) -> GatewayResult:
        """Simulate a gateway refund without external network access."""

        if amount <= 0:
            raise ValueError("Refund amount must be greater than zero.")

        if delay_ms < 0:
            raise ValueError("Delay cannot be negative.")

        if gateway_down:
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="GATEWAY_DOWN",
                message="Mock gateway is unavailable.",
                latency_ms=0,
            )

        await asyncio.sleep(delay_ms / 1000)

        if outcome == "success":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=True,
                status="REFUNDED",
                message="Mock refund succeeded.",
                latency_ms=delay_ms,
            )

        if outcome == "failure":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="REFUND_FAILED",
                message="Mock refund was rejected.",
                latency_ms=delay_ms,
            )

        if outcome == "timeout":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="UNKNOWN",
                message="Refund outcome is unknown due to timeout.",
                latency_ms=delay_ms,
            )

        if outcome == "error":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="ERROR",
                message="Mock gateway refund error.",
                latency_ms=delay_ms,
            )

        raise ValueError(f"Unsupported mock outcome: {outcome}")

    async def fetch_transaction_status(
        self,
        transaction_id: str,
        outcome: MockOutcome = "success",
        delay_ms: int = 50,
        gateway_down: bool = False,
    ) -> GatewayResult:
        """
        Simulate a read-only gateway transaction-status lookup.

        This method never creates or charges a payment.
        """

        if not transaction_id.strip():
            raise ValueError("Transaction ID cannot be empty.")

        if delay_ms < 0:
            raise ValueError("Delay cannot be negative.")

        if gateway_down:
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="GATEWAY_DOWN",
                message="Mock gateway is unavailable.",
                latency_ms=0,
            )

        await asyncio.sleep(delay_ms / 1000)

        if outcome == "success":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=True,
                status="CAPTURED",
                message="Mock gateway confirms successful payment.",
                latency_ms=delay_ms,
            )

        if outcome == "failure":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=True,
                status="FAILED",
                message="Mock gateway confirms payment failure.",
                latency_ms=delay_ms,
            )

        if outcome == "timeout":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="UNKNOWN",
                message="Gateway status lookup timed out.",
                latency_ms=delay_ms,
            )

        if outcome == "error":
            return GatewayResult(
                gateway_name=self.gateway_name,
                success=False,
                status="ERROR",
                message="Mock gateway status lookup failed.",
                latency_ms=delay_ms,
            )

        raise ValueError(f"Unsupported mock outcome: {outcome}")

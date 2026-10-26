from enum import Enum


class PaymentState(str, Enum):
    CREATED = "CREATED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    AUTH_INITIATED = "AUTH_INITIATED"
    AUTHORISED = "AUTHORISED"
    AUTH_FAILED = "AUTH_FAILED"
    AUTH_TIMEOUT = "AUTH_TIMEOUT"
    CAPTURE_INITIATED = "CAPTURE_INITIATED"
    CAPTURED = "CAPTURED"
    PARTIALLY_CAPTURED = "PARTIALLY_CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    REFUND_INITIATED = "REFUND_INITIATED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    REFUND_FAILED = "REFUND_FAILED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"


ALLOWED_TRANSITIONS: dict[PaymentState, set[PaymentState]] = {
    PaymentState.CREATED: {
        PaymentState.ROUTE_SELECTED,
        PaymentState.FAILED,
    },
    PaymentState.ROUTE_SELECTED: {
        PaymentState.AUTH_INITIATED,
        PaymentState.FAILED,
    },
    PaymentState.AUTH_INITIATED: {
        PaymentState.AUTHORISED,
        PaymentState.AUTH_FAILED,
        PaymentState.AUTH_TIMEOUT,
        PaymentState.UNKNOWN,
    },
    PaymentState.AUTH_TIMEOUT: {
        PaymentState.UNKNOWN,
    },
    PaymentState.UNKNOWN: {
        PaymentState.AUTHORISED,
        PaymentState.AUTH_FAILED,
        PaymentState.CAPTURED,
        PaymentState.FAILED,
        PaymentState.RECONCILIATION_MISMATCH,
    },
    PaymentState.AUTHORISED: {
        PaymentState.CAPTURE_INITIATED,
        PaymentState.FAILED,
    },
    PaymentState.CAPTURE_INITIATED: {
        PaymentState.CAPTURED,
        PaymentState.PARTIALLY_CAPTURED,
        PaymentState.CAPTURE_FAILED,
        PaymentState.UNKNOWN,
    },
    PaymentState.PARTIALLY_CAPTURED: {
        PaymentState.CAPTURE_INITIATED,
        PaymentState.REFUND_INITIATED,
        PaymentState.RECONCILIATION_MISMATCH,
    },
    PaymentState.CAPTURED: {
        PaymentState.REFUND_INITIATED,
        PaymentState.RECONCILIATION_MISMATCH,
    },
    PaymentState.CAPTURE_FAILED: {
        PaymentState.CAPTURE_INITIATED,
        PaymentState.UNKNOWN,
    },
    PaymentState.REFUND_INITIATED: {
        PaymentState.REFUNDED,
        PaymentState.PARTIALLY_REFUNDED,
        PaymentState.REFUND_FAILED,
        PaymentState.UNKNOWN,
    },
    PaymentState.PARTIALLY_REFUNDED: {
        PaymentState.REFUND_INITIATED,
        PaymentState.REFUNDED,
        PaymentState.RECONCILIATION_MISMATCH,
    },
    PaymentState.REFUND_FAILED: {
        PaymentState.REFUND_INITIATED,
        PaymentState.UNKNOWN,
    },
    PaymentState.AUTH_FAILED: set(),
    PaymentState.REFUNDED: set(),
    PaymentState.FAILED: set(),
    PaymentState.RECONCILIATION_MISMATCH: {
        PaymentState.CAPTURED,
        PaymentState.PARTIALLY_CAPTURED,
        PaymentState.REFUNDED,
        PaymentState.PARTIALLY_REFUNDED,
        PaymentState.FAILED,
        PaymentState.UNKNOWN,
    },
}


class InvalidStateTransition(ValueError):
    """Raised when a payment state change is not permitted."""


class PaymentStateMachine:
    @staticmethod
    def validate(
        current: PaymentState,
        target: PaymentState,
    ) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, set())

        if target not in allowed:
            raise InvalidStateTransition(
                f"Transition from {current.value} "
                f"to {target.value} is not allowed"
            )

    @classmethod
    def transition(
        cls,
        current: PaymentState,
        target: PaymentState,
    ) -> PaymentState:
        cls.validate(current, target)
        return target

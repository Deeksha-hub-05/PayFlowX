import pytest

from app.domain.state_machine import (
    InvalidStateTransition,
    PaymentState,
    PaymentStateMachine,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaymentState.CREATED, PaymentState.ROUTE_SELECTED),
        (PaymentState.ROUTE_SELECTED, PaymentState.AUTH_INITIATED),
        (PaymentState.AUTH_INITIATED, PaymentState.AUTHORISED),
        (PaymentState.AUTH_INITIATED, PaymentState.AUTH_FAILED),
        (PaymentState.AUTH_INITIATED, PaymentState.AUTH_TIMEOUT),
        (PaymentState.AUTH_INITIATED, PaymentState.UNKNOWN),
        (PaymentState.AUTHORISED, PaymentState.CAPTURE_INITIATED),
        (PaymentState.CAPTURE_INITIATED, PaymentState.CAPTURED),
        (PaymentState.CAPTURE_INITIATED, PaymentState.PARTIALLY_CAPTURED),
        (PaymentState.CAPTURE_INITIATED, PaymentState.UNKNOWN),
        (PaymentState.CAPTURED, PaymentState.REFUND_INITIATED),
        (PaymentState.REFUND_INITIATED, PaymentState.REFUNDED),
        (PaymentState.REFUND_INITIATED, PaymentState.PARTIALLY_REFUNDED),
        (PaymentState.REFUND_INITIATED, PaymentState.UNKNOWN),
        (PaymentState.UNKNOWN, PaymentState.AUTHORISED),
        (PaymentState.UNKNOWN, PaymentState.CAPTURED),
        (PaymentState.PARTIALLY_REFUNDED, PaymentState.REFUNDED),
        (PaymentState.CAPTURED, PaymentState.RECONCILIATION_MISMATCH),
        (PaymentState.RECONCILIATION_MISMATCH, PaymentState.UNKNOWN),
        (PaymentState.CREATED, PaymentState.FAILED),
    ],
)
def test_valid_transitions(current, target):
    assert PaymentStateMachine.transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PaymentState.CREATED, PaymentState.REFUNDED),
        (PaymentState.CREATED, PaymentState.CAPTURED),
        (PaymentState.CREATED, PaymentState.AUTHORISED),
        (PaymentState.AUTH_FAILED, PaymentState.AUTHORISED),
        (PaymentState.AUTH_FAILED, PaymentState.CAPTURED),
        (PaymentState.REFUNDED, PaymentState.CAPTURED),
        (PaymentState.REFUNDED, PaymentState.REFUND_INITIATED),
        (PaymentState.FAILED, PaymentState.AUTHORISED),
        (PaymentState.FAILED, PaymentState.CAPTURED),
        (PaymentState.AUTH_TIMEOUT, PaymentState.ROUTE_SELECTED),
        (PaymentState.AUTH_TIMEOUT, PaymentState.CAPTURED),
        (PaymentState.AUTHORISED, PaymentState.REFUNDED),
        (PaymentState.CAPTURED, PaymentState.AUTH_INITIATED),
        (PaymentState.PARTIALLY_CAPTURED, PaymentState.REFUNDED),
        (PaymentState.REFUND_FAILED, PaymentState.CAPTURED),
    ],
)
def test_invalid_transitions_raise(current, target):
    with pytest.raises(InvalidStateTransition):
        PaymentStateMachine.transition(current, target)

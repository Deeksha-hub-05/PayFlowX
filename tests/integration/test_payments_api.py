
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.api import payments
from app.models.transaction import Transaction


TEST_TRANSACTION_ID = uuid4()


class FakeAsyncSession:
    async def __aenter__(self):
        self.session = AsyncMock()
        self.session.add = MagicMock()

        saved_transaction = SimpleNamespace(
            id=TEST_TRANSACTION_ID,
            merchant_id="merchant_test",
            amount=10000,
            currency="INR",
            payment_method="UPI",
            status="CAPTURED",
            gateway_name="Stripe",
        )

        result = MagicMock()
        result.scalar_one.return_value = saved_transaction

        self.session.execute = AsyncMock(return_value=result)
        self.session.refresh = AsyncMock()

        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.fixture
def client():
    async def override_get_db():
        db = AsyncMock()

        def fake_add(obj):
            if isinstance(obj, Transaction):
                obj.id = TEST_TRANSACTION_ID

        db.add = MagicMock(side_effect=fake_add)

        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(return_value=empty_result)

        yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_payment_rejects_invalid_amount(client):
    response = client.post(
        "/api/v1/payments",
        json={
            "merchant_id": "merchant_test",
            "amount": 0,
            "currency": "INR",
            "payment_method": "UPI",
            "idempotency_key": "invalid-amount-001",
        },
    )

    assert response.status_code == 422


def test_payment_rejects_unsupported_payment_method(client):
    response = client.post(
        "/api/v1/payments",
        json={
            "merchant_id": "merchant_test",
            "amount": 10000,
            "currency": "INR",
            "payment_method": "BITCOIN",
            "idempotency_key": "unsupported-method-001",
        },
    )

    assert response.status_code == 422


def test_payment_fails_over_to_next_gateway(client, monkeypatch):
    routes = [
        MagicMock(
            gateway_name="Razorpay",
            payment_method="UPI",
            priority=1,
        ),
        MagicMock(
            gateway_name="Stripe",
            payment_method="UPI",
            priority=2,
        ),
    ]

    monkeypatch.setattr(
        payments,
        "select_gateways",
        AsyncMock(return_value=routes),
    )

    monkeypatch.setattr(
        payments,
        "AsyncSessionLocal",
        lambda: FakeAsyncSession(),
    )
    monkeypatch.setattr(
        payments,
        "update_gateway_breaker",
        AsyncMock(),
    )

    async def fake_record_transition(
        db,
        transaction_id,
        current_state,
        target_state,
        reason,
    ):
        return target_state

    monkeypatch.setattr(
        payments,
        "record_transition",
        fake_record_transition,
    )

    gateway_results = [
        MagicMock(
            gateway_name="Razorpay",
            success=False,
            status="GATEWAY_DOWN",
            message="Razorpay unavailable",
            latency_ms=0,
        ),
        MagicMock(
            gateway_name="Stripe",
            success=True,
            status="SUCCEEDED",
            message="Payment successful",
            latency_ms=100,
        ),
    ]

    process_mock = AsyncMock(side_effect=gateway_results)

    monkeypatch.setattr(
        payments,
        "process_mock_payment",
        process_mock,
    )

    failover_mock = AsyncMock()

    monkeypatch.setattr(
        payments,
        "record_gateway_failover",
        failover_mock,
    )

    response = client.post(
        "/api/v1/payments",
        headers={
            "X-Mock-Response": "success",
        },
        json={
            "merchant_id": "merchant_test",
            "amount": 10000,
            "currency": "INR",
            "payment_method": "UPI",
            "idempotency_key": "failover-test-001",
        },
    )

    print("HTTP STATUS:", response.status_code)
    print("HTTP RESPONSE:", response.text)
    print("GATEWAY CALL COUNT:", process_mock.await_count)

    assert response.status_code == 201
    assert response.json()["status"] == "CAPTURED"
    assert process_mock.await_count == 2

    assert (
        process_mock.await_args_list[0].kwargs["gateway_name"]
        == "Razorpay"
    )

    assert (
        process_mock.await_args_list[1].kwargs["gateway_name"]
        == "Stripe"
    )

    failover_mock.assert_awaited_once_with(
        TEST_TRANSACTION_ID,
        "Razorpay",
        "Stripe",
    )

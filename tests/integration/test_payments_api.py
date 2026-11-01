
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
    # Create the mock database before the test starts.
    db = AsyncMock()

    def fake_add(obj):
        if isinstance(obj, Transaction):
            obj.id = TEST_TRANSACTION_ID

    db.add = MagicMock(side_effect=fake_add)

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(return_value=empty_result)

    # Make the database accessible to individual tests.
    app.state.test_db = db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()

    if hasattr(app.state, "test_db"):
        del app.state.test_db


# ==================================================
# PAYMENT VALIDATION TESTS
# ==================================================

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


# ==================================================
# PAYMENT GATEWAY FAILOVER TEST
# ==================================================

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


# ==================================================
# GET PAYMENT TESTS
# ==================================================

def test_get_payment_success(client):
    transaction = SimpleNamespace(
        id=TEST_TRANSACTION_ID,
        merchant_id="merchant_test",
        amount=10000,
        currency="INR",
        payment_method="UPI",
        status="CAPTURED",
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = transaction

    app.state.test_db.execute = AsyncMock(return_value=result)

    response = client.get(
        f"/api/v1/payments/{TEST_TRANSACTION_ID}",
        params={
            "merchant_id": "merchant_test",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(TEST_TRANSACTION_ID)
    assert response.json()["merchant_id"] == "merchant_test"
    assert response.json()["amount"] == 10000
    assert response.json()["status"] == "CAPTURED"


def test_get_payment_not_found(client):
    response = client.get(
        f"/api/v1/payments/{uuid4()}",
        params={
            "merchant_id": "merchant_test",
        },
    )

    assert response.status_code == 404


def test_get_payment_rejects_another_merchant(client):
    response = client.get(
        f"/api/v1/payments/{TEST_TRANSACTION_ID}",
        params={
            "merchant_id": "different_merchant",
        },
    )

    assert response.status_code == 404


# ==================================================
# LIST PAYMENTS TESTS
# ==================================================

def test_list_payments_success(client):
    transactions = [
        SimpleNamespace(
            id=uuid4(),
            merchant_id="merchant_test",
            amount=10000,
            currency="INR",
            payment_method="UPI",
            status="CAPTURED",
        ),
        SimpleNamespace(
            id=uuid4(),
            merchant_id="merchant_test",
            amount=20000,
            currency="INR",
            payment_method="CARD",
            status="CAPTURED",
        ),
    ]

    result = MagicMock()
    result.scalars.return_value.all.return_value = transactions

    app.state.test_db.execute = AsyncMock(return_value=result)

    response = client.get(
        "/api/v1/payments",
        params={
            "merchant_id": "merchant_test",
        },
    )

    assert response.status_code == 200
    assert len(response.json()) == 2

    assert all(
        payment["merchant_id"] == "merchant_test"
        for payment in response.json()
    )


def test_list_payments_pagination(client):
    result = MagicMock()
    result.scalars.return_value.all.return_value = []

    app.state.test_db.execute = AsyncMock(return_value=result)

    response = client.get(
        "/api/v1/payments",
        params={
            "merchant_id": "merchant_test",
            "limit": 5,
            "offset": 10,
        },
    )

    assert response.status_code == 200
    assert response.json() == []

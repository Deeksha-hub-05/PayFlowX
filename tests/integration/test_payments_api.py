from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


@pytest.fixture
def client():
    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_payment_rejects_invalid_amount(client):
    response = client.post(
        "/api/v1/payments",
        json={
            "merchant_id": "merchant_test_001",
            "amount": 0,
            "currency": "INR",
            "payment_method": "UPI",
            "idempotency_key": "invalid-amount-test",
        },
    )

    assert response.status_code == 422


def test_payment_rejects_unsupported_payment_method(client):
    response = client.post(
        "/api/v1/payments",
        json={
            "merchant_id": "merchant_test_001",
            "amount": 42000,
            "currency": "INR",
            "payment_method": "CHEQUE",
            "idempotency_key": "invalid-method-test",
        },
    )

    assert response.status_code == 422
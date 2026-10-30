import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db

def test_webhook_rejects_missing_event_id():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhooks/Razorpay",
            json={
                "gateway_name": "Razorpay",
                "event_type": "payment.captured",
                "transaction_id": "12345678-1234-1234-1234-123456789012",
                "status": "CAPTURED",
            },
        )

    assert response.status_code == 422


def test_webhook_rejects_unsupported_gateway():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhooks/UnknownGateway",
            json={
                "gateway_name": "UnknownGateway",
                "event_id": "event_test_001",
                "event_type": "payment.captured",
                "transaction_id": "12345678-1234-1234-1234-123456789012",
                "status": "CAPTURED",
            },
        )

    assert response.status_code == 422


def test_webhook_rejects_invalid_event_type():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/webhooks/Razorpay",
            json={
                "gateway_name": "Razorpay",
                "event_id": "event_test_002",
                "event_type": "payment.unknown",
                "transaction_id": "12345678-1234-1234-1234-123456789012",
                "status": "CAPTURED",
            },
        )

    assert response.status_code == 422

def test_webhook_processes_authorization():
    transaction_id = uuid.uuid4()

    transaction = SimpleNamespace(
        id=transaction_id,
        status="AUTH_INITIATED",
        gateway_name="Razorpay",
    )

    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            duplicate_result,
            transaction_result,
        ]
    )
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/webhooks/Razorpay",
                json={
                    "gateway_name": "Razorpay",
                    "event_id": "event_auth_001",
                    "event_type": "payment.authorized",
                    "transaction_id": str(transaction_id),
                    "status": "AUTHORISED",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "processed"
        assert transaction.status == "AUTHORISED"
        assert mock_db.add.call_count == 3
        mock_db.commit.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
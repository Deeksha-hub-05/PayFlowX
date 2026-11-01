
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.gateways.mock_gateway import GatewayResult
from app.api import reconciliation


@pytest.fixture
def reconciliation_client(monkeypatch):
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(return_value=empty_result)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async def mock_status_lookup(
        gateway_name,
        transaction_id,
        outcome="success",
        delay_ms=50,
        gateway_down=False,
    ):
        if gateway_down:
            status = "GATEWAY_DOWN"
            success = False
        elif outcome == "success":
            status = "CAPTURED"
            success = True
        elif outcome == "failure":
            status = "FAILED"
            success = True
        elif outcome == "timeout":
            status = "UNKNOWN"
            success = False
        else:
            status = "ERROR"
            success = False

        return GatewayResult(
            gateway_name=gateway_name,
            success=success,
            status=status,
            message="Mock reconciliation response.",
            latency_ms=delay_ms,
        )

    monkeypatch.setattr(
        reconciliation,
        "fetch_mock_transaction_status",
        mock_status_lookup,
    )

    with TestClient(app) as client:
        yield client, db

    app.dependency_overrides.clear()


def make_transaction(status="UNKNOWN"):
    return MagicMock(
        id=uuid4(),
        merchant_id="merchant_001",
        amount=10000,
        currency="INR",
        payment_method="UPI",
        gateway_name="Razorpay",
        status=status,
    )


def make_reconciliation_log(
    transaction_id=None,
    result="RECONCILED",
):
    return MagicMock(
        id=uuid4(),
        transaction_id=transaction_id or uuid4(),
        gateway_name="Razorpay",
        previous_status="UNKNOWN",
        reconciled_status="CAPTURED",
        result=result,
        details="Mock reconciliation details.",
        created_at=None,
    )


def configure_transaction_lookup(db, transaction):
    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = transaction

    second_result = MagicMock()
    second_result.scalar_one_or_none.return_value = transaction

    db.execute = AsyncMock(
        side_effect=[first_result, second_result]
    )


# ==========================================
# 1. SUCCESSFUL RECONCILIATION
# ==========================================

def test_successful_reconciliation(reconciliation_client):
    client, db = reconciliation_client

    transaction = make_transaction(status="UNKNOWN")
    configure_transaction_lookup(db, transaction)

    response = client.post(
        f"/api/v1/reconciliation/{transaction.id}"
    )

    assert response.status_code == 200
    assert response.json()["gateway_status"] == "CAPTURED"
    assert response.json()["current_status"] == "CAPTURED"
    assert response.json()["result"] == "RECONCILED"

    assert transaction.status == "CAPTURED"
    assert db.commit.await_count == 2


# ==========================================
# 2. CONFIRMED PAYMENT FAILURE
# ==========================================

def test_reconciliation_confirms_failure(reconciliation_client):
    client, db = reconciliation_client

    transaction = make_transaction(status="UNKNOWN")
    configure_transaction_lookup(db, transaction)

    response = client.post(
        f"/api/v1/reconciliation/{transaction.id}",
        headers={"X-Mock-Response": "failure"},
    )

    assert response.status_code == 200
    assert response.json()["gateway_status"] == "FAILED"
    assert response.json()["current_status"] == "FAILED"
    assert response.json()["result"] == "RECONCILED"

    assert transaction.status == "FAILED"


# ==========================================
# 3. GATEWAY TIMEOUT
# ==========================================

def test_reconciliation_timeout_preserves_status(
    reconciliation_client,
):
    client, db = reconciliation_client

    transaction = make_transaction(status="UNKNOWN")
    configure_transaction_lookup(db, transaction)

    response = client.post(
        f"/api/v1/reconciliation/{transaction.id}",
        headers={"X-Mock-Response": "timeout"},
    )

    assert response.status_code == 200
    assert response.json()["gateway_status"] == "UNKNOWN"
    assert response.json()["current_status"] == "UNKNOWN"
    assert response.json()["result"] == "UNKNOWN"

    assert transaction.status == "UNKNOWN"


# ==========================================
# 4. GATEWAY UNAVAILABLE
# ==========================================

def test_reconciliation_gateway_down(reconciliation_client):
    client, db = reconciliation_client

    transaction = make_transaction(status="UNKNOWN")
    configure_transaction_lookup(db, transaction)

    response = client.post(
        f"/api/v1/reconciliation/{transaction.id}",
        headers={"X-Mock-Gateway-Down": "true"},
    )

    assert response.status_code == 200
    assert response.json()["gateway_status"] == "GATEWAY_DOWN"
    assert response.json()["current_status"] == "UNKNOWN"

    assert transaction.status == "UNKNOWN"


# ==========================================
# 5. UNKNOWN TRANSACTION
# ==========================================

def test_reconciliation_unknown_transaction(
    reconciliation_client,
):
    client, db = reconciliation_client

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=result)

    response = client.post(
        f"/api/v1/reconciliation/{uuid4()}"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Transaction not found."


# ==========================================
# 6. LIST RECONCILIATION RECORDS
# ==========================================

def test_list_reconciliation_records(reconciliation_client):
    client, db = reconciliation_client

    log = make_reconciliation_log()

    result = MagicMock()
    result.scalars.return_value.all.return_value = [log]

    db.execute = AsyncMock(return_value=result)

    response = client.get("/api/v1/reconciliation")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["gateway_name"] == "Razorpay"
    assert response.json()["items"][0]["result"] == "RECONCILED"


# ==========================================
# 7. RECONCILIATION HISTORY
# ==========================================

def test_get_reconciliation_history(reconciliation_client):
    client, db = reconciliation_client

    transaction_id = uuid4()
    log = make_reconciliation_log(
        transaction_id=transaction_id
    )

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction_id

    history_result = MagicMock()
    history_result.scalars.return_value.all.return_value = [log]

    db.execute = AsyncMock(
        side_effect=[transaction_result, history_result]
    )

    response = client.get(
        f"/api/v1/reconciliation/{transaction_id}/history"
    )

    assert response.status_code == 200
    assert response.json()["transaction_id"] == str(transaction_id)
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["gateway_name"] == "Razorpay"

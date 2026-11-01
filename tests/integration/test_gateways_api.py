
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


@pytest.fixture
def gateway_client():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def fake_refresh(obj):
        now = datetime.now(timezone.utc)
        obj.id = getattr(obj, "id", None) or 1
        obj.created_at = getattr(obj, "created_at", None) or now
        obj.updated_at = now

    db.refresh = AsyncMock(side_effect=fake_refresh)

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(return_value=empty_result)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, db

    app.dependency_overrides.clear()


def make_gateway(
    gateway_name="Razorpay",
    is_enabled=True,
    timeout_ms=2000,
    max_retries=2,
    cost_per_transaction=1.5,
):
    now = datetime.now(timezone.utc)

    return MagicMock(
        id=1,
        gateway_name=gateway_name,
        is_enabled=is_enabled,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        cost_per_transaction=cost_per_transaction,
        created_at=now,
        updated_at=now,
    )


# ==========================================
# 1. LIST GATEWAYS
# ==========================================

def test_list_gateways(gateway_client):
    client, db = gateway_client

    gateway = make_gateway()

    result = MagicMock()
    result.scalars.return_value.all.return_value = [gateway]

    db.execute = AsyncMock(return_value=result)

    response = client.get("/api/v1/gateways")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["gateway_name"] == "Razorpay"


# ==========================================
# 2. GET GATEWAY DETAILS
# ==========================================

def test_get_gateway_success(gateway_client):
    client, db = gateway_client

    gateway = make_gateway()

    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway

    db.execute = AsyncMock(return_value=result)

    response = client.get("/api/v1/gateways/Razorpay")

    assert response.status_code == 200
    assert response.json()["gateway_name"] == "Razorpay"
    assert response.json()["is_enabled"] is True


def test_get_gateway_not_found(gateway_client):
    client, db = gateway_client

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=result)

    response = client.get("/api/v1/gateways/UnknownGateway")

    assert response.status_code == 404


# ==========================================
# 3. CREATE GATEWAY
# ==========================================

def test_create_gateway_success(gateway_client):
    client, db = gateway_client

    response = client.post(
        "/api/v1/gateways",
        json={
            "gateway_name": "NewGateway",
            "is_enabled": True,
            "timeout_ms": 3000,
            "max_retries": 3,
            "cost_per_transaction": 2.5,
        },
    )

    assert response.status_code == 201
    assert response.json()["gateway_name"] == "NewGateway"
    assert response.json()["timeout_ms"] == 3000
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


def test_create_gateway_rejects_duplicate(gateway_client):
    client, db = gateway_client

    existing_gateway = make_gateway()

    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_gateway

    db.execute = AsyncMock(return_value=result)

    response = client.post(
        "/api/v1/gateways",
        json={
            "gateway_name": "Razorpay",
        },
    )

    assert response.status_code == 409


# ==========================================
# 4. UPDATE GATEWAY
# ==========================================

def test_update_gateway_success(gateway_client):
    client, db = gateway_client

    gateway = make_gateway()

    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway

    db.execute = AsyncMock(return_value=result)

    response = client.put(
        "/api/v1/gateways/Razorpay",
        json={
            "timeout_ms": 5000,
            "max_retries": 4,
        },
    )

    assert response.status_code == 200
    assert response.json()["timeout_ms"] == 5000
    assert response.json()["max_retries"] == 4
    db.commit.assert_awaited_once()


# ==========================================
# 5. ENABLE GATEWAY
# ==========================================

def test_enable_gateway(gateway_client):
    client, db = gateway_client

    gateway = make_gateway(is_enabled=False)

    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway

    db.execute = AsyncMock(return_value=result)

    response = client.patch(
        "/api/v1/gateways/Razorpay/enable"
    )

    assert response.status_code == 200
    assert response.json()["is_enabled"] is True
    db.commit.assert_awaited_once()


# ==========================================
# 6. DISABLE GATEWAY
# ==========================================

def test_disable_gateway(gateway_client):
    client, db = gateway_client

    gateway = make_gateway(is_enabled=True)

    result = MagicMock()
    result.scalar_one_or_none.return_value = gateway

    db.execute = AsyncMock(return_value=result)

    response = client.patch(
        "/api/v1/gateways/Razorpay/disable"
    )

    assert response.status_code == 200
    assert response.json()["is_enabled"] is False
    db.commit.assert_awaited_once()

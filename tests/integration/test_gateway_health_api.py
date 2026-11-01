
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


@pytest.fixture
def health_client():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

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


def make_health_metric(
    gateway_name="Razorpay",
    payment_method="UPI",
    is_healthy=True,
):
    return MagicMock(
        id=uuid4(),
        gateway_name=gateway_name,
        payment_method=payment_method,
        success_count=100,
        failure_count=5,
        average_latency_ms=120.5,
        is_healthy=is_healthy,
        measured_at=datetime.now(timezone.utc),
    )


def make_circuit_breaker(
    gateway_name="Razorpay",
    payment_method="UPI",
    state="OPEN",
):
    return MagicMock(
        id=uuid4(),
        gateway_name=gateway_name,
        payment_method=payment_method,
        state=state,
        failure_count=5,
        failure_threshold=5,
        recovery_timeout_seconds=30,
        last_failure_at=datetime.now(timezone.utc),
        opened_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ==========================================
# 1. LIST GATEWAY HEALTH METRICS
# ==========================================

def test_list_gateway_health_metrics(health_client):
    client, db = health_client

    metric = make_health_metric()

    result = MagicMock()
    result.scalars.return_value.all.return_value = [metric]

    db.execute = AsyncMock(return_value=result)

    response = client.get("/api/v1/gateway-health/metrics")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["gateway_name"] == "Razorpay"
    assert response.json()[0]["is_healthy"] is True


# ==========================================
# 2. FILTER METRICS BY GATEWAY
# ==========================================

def test_filter_metrics_by_gateway(health_client):
    client, db = health_client

    metric = make_health_metric(gateway_name="Stripe")

    result = MagicMock()
    result.scalars.return_value.all.return_value = [metric]

    db.execute = AsyncMock(return_value=result)

    response = client.get(
        "/api/v1/gateway-health/metrics",
        params={"gateway_name": "Stripe"},
    )

    assert response.status_code == 200
    assert response.json()[0]["gateway_name"] == "Stripe"


# ==========================================
# 3. FILTER METRICS BY PAYMENT METHOD
# ==========================================

def test_filter_metrics_by_payment_method(health_client):
    client, db = health_client

    metric = make_health_metric(payment_method="CARD")

    result = MagicMock()
    result.scalars.return_value.all.return_value = [metric]

    db.execute = AsyncMock(return_value=result)

    response = client.get(
        "/api/v1/gateway-health/metrics",
        params={"payment_method": "CARD"},
    )

    assert response.status_code == 200
    assert response.json()[0]["payment_method"] == "CARD"


# ==========================================
# 4. LIST CIRCUIT BREAKERS
# ==========================================

def test_list_circuit_breakers(health_client):
    client, db = health_client

    breaker = make_circuit_breaker()

    result = MagicMock()
    result.scalars.return_value.all.return_value = [breaker]

    db.execute = AsyncMock(return_value=result)

    response = client.get(
        "/api/v1/gateway-health/circuit-breakers"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["gateway_name"] == "Razorpay"
    assert response.json()[0]["state"] == "OPEN"


# ==========================================
# 5. FILTER CIRCUIT BREAKERS
# ==========================================

def test_filter_circuit_breakers(health_client):
    client, db = health_client

    breaker = make_circuit_breaker(
        gateway_name="Stripe",
        payment_method="CARD",
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = [breaker]

    db.execute = AsyncMock(return_value=result)

    response = client.get(
        "/api/v1/gateway-health/circuit-breakers",
        params={
            "gateway_name": "Stripe",
            "payment_method": "CARD",
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["gateway_name"] == "Stripe"
    assert response.json()[0]["payment_method"] == "CARD"


# ==========================================
# 6. RESET CIRCUIT BREAKER
# ==========================================

def test_reset_circuit_breaker(health_client):
    client, db = health_client

    breaker = make_circuit_breaker(
        state="OPEN",
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = breaker

    db.execute = AsyncMock(return_value=result)

    response = client.post(
        "/api/v1/gateway-health/circuit-breakers/Razorpay/UPI/reset"
    )

    assert response.status_code == 200
    assert response.json()["state"] == "CLOSED"
    assert breaker.failure_count == 0
    assert breaker.last_failure_at is None
    assert breaker.opened_at is None

    db.commit.assert_awaited_once()


# ==========================================
# 7. RESET UNKNOWN CIRCUIT BREAKER
# ==========================================

def test_reset_unknown_circuit_breaker(health_client):
    client, db = health_client

    result = MagicMock()
    result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=result)

    response = client.post(
        "/api/v1/gateway-health/circuit-breakers/Unknown/UPI/reset"
    )

    assert response.status_code == 404

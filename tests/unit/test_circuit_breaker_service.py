
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.circuit_breaker_service import (
    CLOSED,
    OPEN,
    HALF_OPEN,
    is_gateway_available,
    record_gateway_success,
    record_gateway_failure,
)


def make_breaker(
    state=CLOSED,
    failure_count=0,
    failure_threshold=5,
    recovery_timeout_seconds=30,
    opened_at=None,
):
    breaker = MagicMock()
    breaker.state = state
    breaker.failure_count = failure_count
    breaker.failure_threshold = failure_threshold
    breaker.recovery_timeout_seconds = recovery_timeout_seconds
    breaker.opened_at = opened_at
    breaker.last_failure_at = None
    breaker.updated_at = None
    return breaker


def make_db(breaker):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = breaker
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_closed_breaker_allows_payment():
    breaker = make_breaker(state=CLOSED)
    db = make_db(breaker)

    available = await is_gateway_available(db, "Razorpay", "UPI")

    assert available is True
    assert breaker.state == CLOSED


@pytest.mark.asyncio
async def test_open_breaker_blocks_payment():
    breaker = make_breaker(
        state=OPEN,
        opened_at=datetime.now(timezone.utc),
    )
    db = make_db(breaker)

    available = await is_gateway_available(db, "Razorpay", "UPI")

    assert available is False
    assert breaker.state == OPEN


@pytest.mark.asyncio
async def test_open_breaker_moves_to_half_open_after_timeout():
    breaker = make_breaker(
        state=OPEN,
        opened_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        recovery_timeout_seconds=30,
    )
    db = make_db(breaker)

    available = await is_gateway_available(db, "Razorpay", "UPI")

    assert available is True
    assert breaker.state == HALF_OPEN
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_resets_breaker():
    breaker = make_breaker(
        state=OPEN,
        failure_count=5,
    )
    db = make_db(breaker)

    await record_gateway_success(db, "Razorpay", "UPI")

    assert breaker.state == CLOSED
    assert breaker.failure_count == 0
    assert breaker.opened_at is None
    assert breaker.last_failure_at is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_five_failures_open_breaker():
    breaker = make_breaker(
        state=CLOSED,
        failure_count=4,
        failure_threshold=5,
    )
    db = make_db(breaker)

    await record_gateway_failure(db, "Razorpay", "UPI")

    assert breaker.failure_count == 5
    assert breaker.state == OPEN
    assert breaker.opened_at is not None
    db.flush.assert_awaited_once()

@pytest.mark.asyncio
async def test_half_open_failure_immediately_reopens_breaker():
    breaker = make_breaker(
        state=HALF_OPEN,
        failure_count=1,
        failure_threshold=5,
    )
    db = make_db(breaker)

    await record_gateway_failure(db, "Razorpay", "UPI")

    assert breaker.failure_count == 2
    assert breaker.state == OPEN
    assert breaker.opened_at is not None
    db.flush.assert_awaited_once()
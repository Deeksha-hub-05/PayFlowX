
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.api import refunds
from app.api.refunds import (
    calculate_reserved_refund_amount,
    create_refund,
    create_state_log,
    finalize_refund,
    find_existing_refund,
    get_refund,
    get_refundable_transaction,
    list_refunds,
    mark_refund_unknown,
    to_refund_response,
)
from app.api.schemas import RefundCreate
from app.domain.state_machine import InvalidStateTransition
from app.models.transaction_state_log import TransactionStateLog


def make_refund_request(
    transaction_id=None,
    amount=500,
    idempotency_key="test-refund-key",
):
    return RefundCreate(
        transaction_id=str(transaction_id or uuid4()),
        merchant_id="merchant_test",
        amount=amount,
        idempotency_key=idempotency_key,
    )


def test_to_refund_response():
    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        amount=500,
        currency="INR",
        status="REFUNDED",
        gateway_name="Razorpay",
        gateway_refund_id="mock-refund-123",
    )

    response = to_refund_response(refund)

    assert response.amount == 500
    assert response.currency == "INR"
    assert response.status == "REFUNDED"
    assert response.gateway_name == "Razorpay"


@pytest.mark.asyncio
async def test_find_existing_refund_returns_none():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    refund = await find_existing_refund(
        db, uuid4(), "test-key", 500
    )

    assert refund is None


@pytest.mark.asyncio
async def test_find_existing_refund_returns_existing():
    db = AsyncMock()
    existing = SimpleNamespace(amount=500)

    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result

    refund = await find_existing_refund(
        db, uuid4(), "test-key", 500
    )

    assert refund is existing


@pytest.mark.asyncio
async def test_find_existing_refund_rejects_different_amount():
    db = AsyncMock()
    existing = SimpleNamespace(amount=500)

    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc:
        await find_existing_refund(
            db, uuid4(), "test-key", 600
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_calculate_reserved_refund_amount():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 1500
    db.execute.return_value = result

    amount = await calculate_reserved_refund_amount(
        db, uuid4()
    )

    assert amount == 1500


@pytest.mark.asyncio
async def test_get_refundable_transaction_success():
    db = AsyncMock()

    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        status="CAPTURED",
        amount=10000,
        currency="INR",
        gateway_name="Razorpay",
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = transaction
    db.execute.return_value = result

    returned = await get_refundable_transaction(
        db, transaction.id, "merchant_test"
    )

    assert returned is transaction


@pytest.mark.asyncio
async def test_get_refundable_transaction_not_found():
    db = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc:
        await get_refundable_transaction(
            db, uuid4(), "unknown_merchant"
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_refundable_transaction_invalid_status():
    db = AsyncMock()

    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        status="CREATED",
        amount=10000,
        currency="INR",
        gateway_name="Razorpay",
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = transaction
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc:
        await get_refundable_transaction(
            db, transaction.id, "merchant_test"
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_state_log():
    db = AsyncMock()
    db.add = MagicMock()

    transaction = SimpleNamespace(id=uuid4())

    await create_state_log(
        db=db,
        transaction=transaction,
        previous_state="CAPTURED",
        new_state="REFUND_INITIATED",
        reason="Refund request initiated.",
    )

    db.add.assert_called_once()

    log_entry = db.add.call_args.args[0]

    assert isinstance(log_entry, TransactionStateLog)
    assert log_entry.transaction_id == transaction.id
    assert log_entry.previous_state == "CAPTURED"
    assert log_entry.new_state == "REFUND_INITIATED"


@pytest.mark.asyncio
async def test_finalize_refund_missing_refund(monkeypatch):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds, "AsyncSessionLocal", lambda: FakeSession()
    )

    with pytest.raises(HTTPException) as exc:
        await finalize_refund(uuid4(), "REFUNDED")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_mark_refund_unknown_missing_refund(monkeypatch):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds, "AsyncSessionLocal", lambda: FakeSession()
    )

    await mark_refund_unknown(uuid4())

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_refund_missing_transaction(monkeypatch):
    db = AsyncMock()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds, "AsyncSessionLocal", lambda: FakeSession()
    )

    with pytest.raises(HTTPException) as exc:
        await finalize_refund(refund.id, "REFUNDED")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_mark_refund_unknown_success(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        status="REFUND_INITIATED",
    )

    transaction = SimpleNamespace(
        id=refund.transaction_id,
        status="REFUND_INITIATED",
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    await mark_refund_unknown(refund.id)

    assert refund.status == "UNKNOWN"
    assert transaction.status == "UNKNOWN"
    db.commit.assert_awaited_once()
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_refund_success(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    transaction_id = uuid4()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction_id,
        amount=10000,
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    transaction = SimpleNamespace(
        id=transaction_id,
        status="REFUND_INITIATED",
        amount=10000,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    amount_result = MagicMock()
    amount_result.scalar_one.return_value = 10000

    db.execute = AsyncMock(
        side_effect=[
            refund_result,
            transaction_result,
            amount_result,
        ]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    result = await finalize_refund(
        refund.id,
        "REFUNDED",
    )

    assert result.status == "REFUNDED"
    assert result.gateway_refund_id.startswith("mock-")
    assert transaction.status == "REFUNDED"
    db.commit.assert_awaited_once()
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_partial_refund(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    transaction_id = uuid4()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction_id,
        amount=2000,
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    transaction = SimpleNamespace(
        id=transaction_id,
        status="REFUND_INITIATED",
        amount=10000,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    amount_result = MagicMock()
    amount_result.scalar_one.return_value = 2000

    db.execute = AsyncMock(
        side_effect=[
            refund_result,
            transaction_result,
            amount_result,
        ]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    result = await finalize_refund(
        refund.id,
        "REFUNDED",
    )

    assert result.status == "REFUNDED"
    assert transaction.status == "PARTIALLY_REFUNDED"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_refund_gateway_failure(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    transaction_id = uuid4()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction_id,
        amount=2000,
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    transaction = SimpleNamespace(
        id=transaction_id,
        status="REFUND_INITIATED",
        amount=10000,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    result = await finalize_refund(
        refund.id,
        "REFUND_FAILED",
    )

    assert result.status == "REFUND_FAILED"
    assert transaction.status == "REFUND_FAILED"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_refund_gateway_down(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    transaction_id = uuid4()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction_id,
        amount=2000,
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    transaction = SimpleNamespace(
        id=transaction_id,
        status="REFUND_INITIATED",
        amount=10000,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    result = await finalize_refund(
        refund.id,
        "GATEWAY_DOWN",
    )

    assert result.status == "REFUND_FAILED"
    assert transaction.status == "REFUND_FAILED"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_refund_unknown(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    transaction_id = uuid4()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction_id,
        amount=2000,
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    transaction = SimpleNamespace(
        id=transaction_id,
        status="REFUND_INITIATED",
        amount=10000,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    result = await finalize_refund(refund.id, "UNKNOWN")

    assert result.status == "UNKNOWN"
    assert transaction.status == "UNKNOWN"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_refund_unknown_missing_transaction(monkeypatch):
    db = AsyncMock()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        status="REFUND_INITIATED",
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    await mark_refund_unknown(refund.id)

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_refund_invalid_transition(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    transaction_id = uuid4()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction_id,
        amount=2000,
        status="REFUND_INITIATED",
        gateway_refund_id=None,
    )

    transaction = SimpleNamespace(
        id=transaction_id,
        status="CREATED",
        amount=10000,
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    amount_result = MagicMock()
    amount_result.scalar_one.return_value = 2000

    db.execute = AsyncMock(
        side_effect=[
            refund_result,
            transaction_result,
            amount_result,
        ]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    with pytest.raises(InvalidStateTransition):
        await finalize_refund(refund.id, "REFUNDED")

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_refund_unknown_invalid_transition(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        status="REFUND_INITIATED",
    )

    transaction = SimpleNamespace(
        id=refund.transaction_id,
        status="CREATED",
    )

    refund_result = MagicMock()
    refund_result.scalar_one_or_none.return_value = refund

    transaction_result = MagicMock()
    transaction_result.scalar_one_or_none.return_value = transaction

    db.execute = AsyncMock(
        side_effect=[refund_result, transaction_result]
    )

    class FakeSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    with pytest.raises(InvalidStateTransition):
        await mark_refund_unknown(refund.id)

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_refund_invalid_transaction_id():
    request = make_refund_request()

    # Bypass Pydantic assignment validation to test endpoint handling.
    object.__setattr__(request, "transaction_id", "invalid-uuid")

    response = Response()

    with pytest.raises(HTTPException) as exc:
        await create_refund(
            refund_data=request,
            response=response,
            db=AsyncMock(),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_refund_existing_idempotency_key(monkeypatch):
    existing = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        amount=500,
        currency="INR",
        status="REFUNDED",
        gateway_name="Razorpay",
        gateway_refund_id="mock-refund-123",
    )

    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=existing),
    )

    response = Response()

    result = await create_refund(
        refund_data=make_refund_request(
            existing.transaction_id
        ),
        response=response,
        db=AsyncMock(),
    )

    assert response.status_code == 200
    assert result.status == "REFUNDED"
    assert result.id == str(existing.id)


@pytest.mark.asyncio
async def test_create_refund_transaction_not_found(monkeypatch):
    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=None),
    )

    async def fake_get_transaction(*args, **kwargs):
        raise HTTPException(
            status_code=404,
            detail="Transaction not found.",
        )

    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        fake_get_transaction,
    )

    response = Response()

    with pytest.raises(HTTPException) as exc:
        await create_refund(
            refund_data=make_refund_request(),
            response=response,
            db=AsyncMock(),
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_refund_without_gateway(monkeypatch):
    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        amount=10000,
        currency="INR",
        status="CAPTURED",
        gateway_name=None,
    )

    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=None),
    )

    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        AsyncMock(return_value=transaction),
    )

    response = Response()

    with pytest.raises(HTTPException) as exc:
        await create_refund(
            refund_data=make_refund_request(transaction.id),
            response=response,
            db=AsyncMock(),
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_refund_exceeds_available_balance(monkeypatch):
    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        amount=1000,
        currency="INR",
        status="CAPTURED",
        gateway_name="Razorpay",
    )

    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=None),
    )

    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        AsyncMock(return_value=transaction),
    )

    monkeypatch.setattr(
        refunds,
        "calculate_reserved_refund_amount",
        AsyncMock(return_value=600),
    )

    response = Response()

    with pytest.raises(HTTPException) as exc:
        await create_refund(
            refund_data=make_refund_request(
                transaction.id,
                amount=500,
            ),
            response=response,
            db=AsyncMock(),
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_refund_success(monkeypatch):
    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        amount=10000,
        currency="INR",
        status="CAPTURED",
        gateway_name="Razorpay",
    )

    async def fake_refresh(refund):
        if refund.id is None:
            refund.id = uuid4()

    db = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock(side_effect=fake_refresh)

    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        AsyncMock(return_value=transaction),
    )
    monkeypatch.setattr(
        refunds,
        "calculate_reserved_refund_amount",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        refunds,
        "create_state_log",
        AsyncMock(),
    )
    monkeypatch.setattr(
        refunds,
        "process_mock_refund",
        AsyncMock(
            return_value=SimpleNamespace(status="REFUNDED")
        ),
    )

    completed_refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction.id,
        amount=500,
        currency="INR",
        status="REFUNDED",
        gateway_name="Razorpay",
        gateway_refund_id="mock-refund-123",
    )

    finalize_mock = AsyncMock(return_value=completed_refund)
    monkeypatch.setattr(
        refunds,
        "finalize_refund",
        finalize_mock,
    )

    response = Response(status_code=201)

    result = await create_refund(
        refund_data=make_refund_request(
            transaction.id,
            amount=500,
        ),
        response=response,
        db=db,
    )

    assert response.status_code == 201
    assert result.status == "REFUNDED"
    assert result.gateway_refund_id == "mock-refund-123"
    db.commit.assert_awaited_once()
    finalize_mock.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_status", "expected_status", "http_status"),
    [
        ("REFUND_FAILED", "REFUND_FAILED", 200),
        ("UNKNOWN", "UNKNOWN", 202),
    ],
)
async def test_create_refund_gateway_result_statuses(
    monkeypatch,
    gateway_status,
    expected_status,
    http_status,
):
    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        amount=10000,
        currency="INR",
        status="CAPTURED",
        gateway_name="Razorpay",
    )

    async def fake_refresh(refund):
        if refund.id is None:
            refund.id = uuid4()

    db = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock(side_effect=fake_refresh)

    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        AsyncMock(return_value=transaction),
    )
    monkeypatch.setattr(
        refunds,
        "calculate_reserved_refund_amount",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        refunds,
        "create_state_log",
        AsyncMock(),
    )
    monkeypatch.setattr(
        refunds,
        "process_mock_refund",
        AsyncMock(
            return_value=SimpleNamespace(status=gateway_status)
        ),
    )

    completed_refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction.id,
        amount=500,
        currency="INR",
        status=expected_status,
        gateway_name="Razorpay",
        gateway_refund_id=None,
    )

    monkeypatch.setattr(
        refunds,
        "finalize_refund",
        AsyncMock(return_value=completed_refund),
    )

    response = Response()

    result = await create_refund(
        refund_data=make_refund_request(
            transaction.id,
            amount=500,
        ),
        response=response,
        db=db,
    )

    assert response.status_code == http_status
    assert result.status == expected_status


@pytest.mark.asyncio
async def test_create_refund_gateway_exception_returns_unknown(
    monkeypatch,
):
    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        amount=10000,
        currency="INR",
        status="CAPTURED",
        gateway_name="Razorpay",
    )

    async def fake_refresh(refund):
        if refund.id is None:
            refund.id = uuid4()

    db = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock(side_effect=fake_refresh)

    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        AsyncMock(return_value=transaction),
    )
    monkeypatch.setattr(
        refunds,
        "calculate_reserved_refund_amount",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        refunds,
        "create_state_log",
        AsyncMock(),
    )
    monkeypatch.setattr(
        refunds,
        "process_mock_refund",
        AsyncMock(side_effect=RuntimeError("Gateway error")),
    )

    mark_unknown_mock = AsyncMock()
    monkeypatch.setattr(
        refunds,
        "mark_refund_unknown",
        mark_unknown_mock,
    )

    updated_refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction.id,
        amount=500,
        currency="INR",
        status="UNKNOWN",
        gateway_name="Razorpay",
        gateway_refund_id=None,
    )

    read_db = AsyncMock()
    read_result = MagicMock()
    read_result.scalar_one.return_value = updated_refund
    read_db.execute.return_value = read_result

    class FakeSession:
        async def __aenter__(self):
            return read_db

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        refunds,
        "AsyncSessionLocal",
        lambda: FakeSession(),
    )

    response = Response()

    result = await create_refund(
        refund_data=make_refund_request(
            transaction.id,
            amount=500,
        ),
        response=response,
        db=db,
    )

    assert response.status_code == 202
    assert result.status == "UNKNOWN"
    mark_unknown_mock.assert_awaited_once()
    read_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_refund_integrity_error_returns_existing(
    monkeypatch,
):
    from sqlalchemy.exc import IntegrityError

    transaction = SimpleNamespace(
        id=uuid4(),
        merchant_id="merchant_test",
        amount=10000,
        currency="INR",
        status="CAPTURED",
        gateway_name="Razorpay",
    )

    existing_refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=transaction.id,
        amount=500,
        currency="INR",
        status="REFUNDED",
        gateway_name="Razorpay",
        gateway_refund_id="mock-refund-existing",
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.commit.side_effect = IntegrityError(
        "INSERT",
        {},
        Exception("duplicate key"),
    )

    find_mock = AsyncMock(
        side_effect=[None, existing_refund]
    )
    monkeypatch.setattr(
        refunds,
        "find_existing_refund",
        find_mock,
    )
    monkeypatch.setattr(
        refunds,
        "get_refundable_transaction",
        AsyncMock(return_value=transaction),
    )
    monkeypatch.setattr(
        refunds,
        "calculate_reserved_refund_amount",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        refunds,
        "create_state_log",
        AsyncMock(),
    )

    gateway_mock = AsyncMock()
    monkeypatch.setattr(
        refunds,
        "process_mock_refund",
        gateway_mock,
    )

    response = Response()

    result = await create_refund(
        refund_data=make_refund_request(
            transaction.id,
            amount=500,
        ),
        response=response,
        db=db,
    )

    assert response.status_code == 200
    assert result.id == str(existing_refund.id)
    assert result.status == "REFUNDED"
    db.rollback.assert_awaited_once()
    gateway_mock.assert_not_awaited()


    # --------------------------------------------------
# Tests for GET /api/v1/refunds
# --------------------------------------------------

@pytest.mark.asyncio
async def test_list_refunds_success():
    db = AsyncMock()

    refund = SimpleNamespace(
        id=uuid4(),
        transaction_id=uuid4(),
        amount=500,
        currency="INR",
        status="REFUNDED",
        gateway_name="Razorpay",
        gateway_refund_id="mock-refund-123",
    )

    result = MagicMock()
    result.scalars.return_value.all.return_value = [refund]
    db.execute.return_value = result

    response = await list_refunds(
        merchant_id="merchant_test",
        limit=20,
        offset=0,
        db=db,
    )

    assert len(response) == 1
    assert response[0].amount == 500
    assert response[0].status == "REFUNDED"
    assert response[0].gateway_name == "Razorpay"
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_refunds_empty():
    db = AsyncMock()

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    response = await list_refunds(
        merchant_id="merchant_test",
        limit=20,
        offset=0,
        db=db,
    )

    assert response == []
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_refund_success():
    db = AsyncMock()
    refund_id = uuid4()

    refund = SimpleNamespace(
        id=refund_id,
        transaction_id=uuid4(),
        amount=500,
        currency="INR",
        status="REFUNDED",
        gateway_name="Razorpay",
        gateway_refund_id="mock-refund-123",
    )

    result = MagicMock()
    result.scalar_one_or_none.return_value = refund
    db.execute.return_value = result

    response = await get_refund(
        refund_id=refund_id,
        merchant_id="merchant_test",
        db=db,
    )

    assert response.id == str(refund_id)
    assert response.amount == 500
    assert response.status == "REFUNDED"
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_refund_not_found():
    db = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc:
        await get_refund(
            refund_id=uuid4(),
            merchant_id="merchant_test",
            db=db,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Refund not found."
    db.execute.assert_awaited_once()

import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PaymentCreate, PaymentResponse
from app.database import AsyncSessionLocal, get_db
from app.domain.state_machine import PaymentState, PaymentStateMachine
from app.models.idempotency_key import IdempotencyKey
from app.models.transaction import Transaction
from app.models.transaction_state_log import TransactionStateLog
from app.services.payment_service import process_mock_payment
from app.services.routing_service import select_gateway

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])

MockOutcome = Literal["success", "failure", "timeout", "error"]


def make_request_hash(payment: PaymentCreate) -> str:
    """Create a stable hash of payment details, excluding the idempotency key."""
    payload = payment.model_dump(exclude={"idempotency_key"})
    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def to_payment_response(transaction: Transaction) -> PaymentResponse:
    return PaymentResponse(
        id=str(transaction.id),
        merchant_id=transaction.merchant_id,
        amount=transaction.amount,
        currency=transaction.currency,
        payment_method=transaction.payment_method,
        status=transaction.status,
    )


async def find_existing_payment(
    db: AsyncSession,
    merchant_id: str,
    idempotency_key: str,
    request_hash: str,
) -> Transaction | None:
    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.merchant_id == merchant_id,
            IdempotencyKey.key == idempotency_key,
        )
    )
    saved_key = result.scalar_one_or_none()

    if saved_key is None:
        return None

    if saved_key.request_hash != request_hash:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used with different payment details.",
        )

    if saved_key.transaction_id is None:
        raise HTTPException(
            status_code=409,
            detail="A request using this idempotency key is still in progress.",
        )

    result = await db.execute(
        select(Transaction).where(Transaction.id == saved_key.transaction_id)
    )
    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=409,
            detail="The original transaction could not be found.",
        )

    return transaction


async def record_transition(
    db: AsyncSession,
    transaction_id,
    current_state: PaymentState,
    target_state: PaymentState,
    reason: str,
) -> PaymentState:
    """Validate and persist a single state transition."""
    PaymentStateMachine.validate(current_state, target_state)

    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = result.scalar_one_or_none()
    if transaction is None:
        raise RuntimeError("Transaction disappeared while processing payment.")

    transaction.status = target_state.value
    db.add(
        TransactionStateLog(
            transaction_id=transaction.id,
            previous_state=current_state.value,
            new_state=target_state.value,
            reason=reason,
        )
    )
    await db.commit()
    return target_state


@router.post("", response_model=PaymentResponse, status_code=201)
async def create_payment(
    payment: PaymentCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    mock_response: MockOutcome = Header(default="success", alias="X-Mock-Response"),
    mock_delay_ms: int = Header(default=50, alias="X-Mock-Delay-Ms", ge=0, le=10000),
    mock_gateway_down: bool = Header(default=False, alias="X-Mock-Gateway-Down"),
):
    """Create a payment, route it, and persist validated state transitions."""
    request_hash = make_request_hash(payment)

    existing = await find_existing_payment(
        db,
        payment.merchant_id,
        payment.idempotency_key,
        request_hash,
    )
    if existing is not None:
        response.status_code = 200
        return to_payment_response(existing)

    route = await select_gateway(db, payment.payment_method)
    if route is None:
        raise HTTPException(
            status_code=503,
            detail=f"No enabled gateway supports {payment.payment_method}.",
        )

    transaction = Transaction(
        merchant_id=payment.merchant_id,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        status=PaymentState.CREATED.value,
        gateway_name=route.gateway_name,
    )

    try:
        db.add(transaction)
        await db.flush()

        db.add(
            TransactionStateLog(
                transaction_id=transaction.id,
                previous_state=None,
                new_state=PaymentState.CREATED.value,
                reason="Payment transaction created",
            )
        )
        db.add(
            IdempotencyKey(
                merchant_id=payment.merchant_id,
                key=payment.idempotency_key,
                transaction_id=transaction.id,
                request_hash=request_hash,
            )
        )
        await db.commit()
        transaction_id = transaction.id

    except IntegrityError:
        await db.rollback()
        existing = await find_existing_payment(
            db,
            payment.merchant_id,
            payment.idempotency_key,
            request_hash,
        )
        if existing is not None:
            response.status_code = 200
            return to_payment_response(existing)
        raise

    # Persist route selection and authorization initiation before calling the gateway.
    try:
        async with AsyncSessionLocal() as state_db:
            current_state = PaymentState.CREATED
            current_state = await record_transition(
                state_db,
                transaction_id,
                current_state,
                PaymentState.ROUTE_SELECTED,
                f"Selected gateway {route.gateway_name}",
            )
            current_state = await record_transition(
                state_db,
                transaction_id,
                current_state,
                PaymentState.AUTH_INITIATED,
                "Mock gateway authorization initiated",
            )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not persist payment authorization state.",
        ) from exc

    # Do not hold a database session while waiting for the gateway.
    try:
        gateway_result = await process_mock_payment(
            gateway_name=route.gateway_name,
            amount=payment.amount,
            payment_method=payment.payment_method,
            outcome=mock_response,
            delay_ms=mock_delay_ms,
            gateway_down=mock_gateway_down,
        )
    except Exception as exc:
        # We cannot safely assume a gateway error means the payment failed.
        try:
            async with AsyncSessionLocal() as state_db:
                await record_transition(
                    state_db,
                    transaction_id,
                    PaymentState.AUTH_INITIATED,
                    PaymentState.UNKNOWN,
                    f"Gateway processing raised an exception: {type(exc).__name__}",
                )
        except Exception:
            pass
        raise HTTPException(
            status_code=502,
            detail="Gateway processing failed unexpectedly; payment outcome may require reconciliation.",
        ) from exc

    try:
        async with AsyncSessionLocal() as state_db:
            if gateway_result.status == "SUCCEEDED":
                current_state = await record_transition(
                    state_db,
                    transaction_id,
                    PaymentState.AUTH_INITIATED,
                    PaymentState.AUTHORISED,
                    f"Gateway authorization approved: {gateway_result.message}",
                )
                current_state = await record_transition(
                    state_db,
                    transaction_id,
                    current_state,
                    PaymentState.CAPTURE_INITIATED,
                    "Full payment capture initiated",
                )
                await record_transition(
                    state_db,
                    transaction_id,
                    current_state,
                    PaymentState.CAPTURED,
                    (
                        f"Gateway {gateway_result.gateway_name}: payment captured; "
                        f"latency_ms={gateway_result.latency_ms}"
                    ),
                )

            elif gateway_result.status == "FAILED":
                await record_transition(
                    state_db,
                    transaction_id,
                    PaymentState.AUTH_INITIATED,
                    PaymentState.AUTH_FAILED,
                    (
                        f"Gateway {gateway_result.gateway_name}: "
                        f"{gateway_result.message}; latency_ms={gateway_result.latency_ms}"
                    ),
                )

            else:
                await record_transition(
                    state_db,
                    transaction_id,
                    PaymentState.AUTH_INITIATED,
                    PaymentState.UNKNOWN,
                    (
                        f"Gateway {gateway_result.gateway_name}: "
                        f"{gateway_result.status} - {gateway_result.message}; "
                        f"latency_ms={gateway_result.latency_ms}"
                    ),
                )

            result = await state_db.execute(
                select(Transaction).where(Transaction.id == transaction_id)
            )
            saved_transaction = result.scalar_one()
            await state_db.refresh(saved_transaction)
            return to_payment_response(saved_transaction)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not persist the final payment state.",
        ) from exc

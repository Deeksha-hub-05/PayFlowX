
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PaymentCreate, PaymentResponse
from app.database import get_db
from app.models.idempotency_key import IdempotencyKey
from app.models.transaction import Transaction

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


def make_request_hash(payment: PaymentCreate) -> str:
    """Create a stable hash of the payment details, excluding the key."""
    payload = payment.model_dump(exclude={"idempotency_key"})
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


async def find_existing_payment(
    db: AsyncSession,
    merchant_id: str,
    idempotency_key: str,
    request_hash: str,
) -> Transaction | None:
    """Return the original transaction, or reject unsafe key reuse."""
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


def to_payment_response(transaction: Transaction) -> PaymentResponse:
    return PaymentResponse(
        id=str(transaction.id),
        merchant_id=transaction.merchant_id,
        amount=transaction.amount,
        currency=transaction.currency,
        payment_method=transaction.payment_method,
        status=transaction.status,
    )


@router.post("", response_model=PaymentResponse, status_code=201)
async def create_payment(
    payment: PaymentCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create a payment once per merchant and idempotency key."""
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

    transaction = Transaction(
        merchant_id=payment.merchant_id,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        status="CREATED",
    )

    try:
        db.add(transaction)
        await db.flush()

        db.add(
            IdempotencyKey(
                merchant_id=payment.merchant_id,
                key=payment.idempotency_key,
                transaction_id=transaction.id,
                request_hash=request_hash,
            )
        )

        await db.commit()
        await db.refresh(transaction)

    except IntegrityError:
        await db.rollback()

        # Another simultaneous request may have saved this key first.
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

    return to_payment_response(transaction)

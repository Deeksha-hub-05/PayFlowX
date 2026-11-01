
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import RefundCreate, RefundResponse
from app.database import AsyncSessionLocal, get_db
from app.domain.state_machine import PaymentState, PaymentStateMachine
from app.models.refund import Refund
from app.models.transaction import Transaction
from app.models.transaction_state_log import TransactionStateLog
from app.services.payment_service import process_mock_refund


router = APIRouter(prefix="/api/v1/refunds", tags=["Refunds"])

MockOutcome = Literal["success", "failure", "timeout", "error"]


def to_refund_response(refund: Refund) -> RefundResponse:
    return RefundResponse(
        id=str(refund.id),
        transaction_id=str(refund.transaction_id),
        amount=refund.amount,
        currency=refund.currency,
        status=refund.status,
        gateway_name=refund.gateway_name,
        gateway_refund_id=refund.gateway_refund_id,
    )


async def find_existing_refund(
    db: AsyncSession,
    transaction_id: UUID,
    idempotency_key: str,
    amount: int,
) -> Refund | None:
    result = await db.execute(
        select(Refund).where(
            Refund.transaction_id == transaction_id,
            Refund.idempotency_key == idempotency_key,
        )
    )

    existing = result.scalar_one_or_none()

    if existing is None:
        return None

    if existing.amount != amount:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used with a different refund amount.",
        )

    return existing


async def calculate_reserved_refund_amount(
    db: AsyncSession,
    transaction_id: UUID,
) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.transaction_id == transaction_id,
            Refund.status.in_(
                ["REFUND_INITIATED", "UNKNOWN", "REFUNDED"]
            ),
        )
    )

    return int(result.scalar_one())


async def get_refundable_transaction(
    db: AsyncSession,
    transaction_id: UUID,
    merchant_id: str,
) -> Transaction:
    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.id == transaction_id,
            Transaction.merchant_id == merchant_id,
        )
        .with_for_update()
    )

    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found.",
        )

    allowed_states = {
        PaymentState.CAPTURED.value,
        PaymentState.PARTIALLY_REFUNDED.value,
        PaymentState.REFUND_FAILED.value,
    }

    if transaction.status not in allowed_states:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaction cannot be refunded from status "
                f"{transaction.status}."
            ),
        )

    return transaction


async def create_state_log(
    db: AsyncSession,
    transaction: Transaction,
    previous_state: str,
    new_state: str,
    reason: str,
) -> None:
    db.add(
        TransactionStateLog(
            transaction_id=transaction.id,
            previous_state=previous_state,
            new_state=new_state,
            reason=reason,
        )
    )


async def mark_refund_unknown(refund_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Refund).where(Refund.id == refund_id)
        )
        refund = result.scalar_one_or_none()

        if refund is None:
            return

        transaction_result = await db.execute(
            select(Transaction)
            .where(Transaction.id == refund.transaction_id)
            .with_for_update()
        )
        transaction = transaction_result.scalar_one_or_none()

        if transaction is None:
            return

        refund.status = PaymentState.UNKNOWN.value

        current_state = PaymentState(transaction.status)
        target_state = PaymentState.UNKNOWN

        PaymentStateMachine.validate(current_state, target_state)

        transaction.status = target_state.value

        await create_state_log(
            db,
            transaction,
            current_state.value,
            target_state.value,
            "Refund gateway response was uncertain; reconciliation required.",
        )

        await db.commit()


async def finalize_refund(
    refund_id: UUID,
    gateway_status: str,
) -> Refund:
    async with AsyncSessionLocal() as db:
        refund_result = await db.execute(
            select(Refund).where(Refund.id == refund_id)
        )
        refund = refund_result.scalar_one_or_none()

        if refund is None:
            raise HTTPException(
                status_code=404,
                detail="Refund record not found.",
            )

        transaction_result = await db.execute(
            select(Transaction)
            .where(Transaction.id == refund.transaction_id)
            .with_for_update()
        )
        transaction = transaction_result.scalar_one_or_none()

        if transaction is None:
            raise HTTPException(
                status_code=404,
                detail="Transaction not found.",
            )

        current_state = PaymentState(transaction.status)

        if gateway_status == "REFUNDED":
            refund.status = PaymentState.REFUNDED.value
            refund.gateway_refund_id = f"mock-{uuid4()}"

            total_refunded = await calculate_reserved_refund_amount(
                db,
                transaction.id,
            )

            target_state = (
                PaymentState.REFUNDED
                if total_refunded >= transaction.amount
                else PaymentState.PARTIALLY_REFUNDED
            )

        elif gateway_status in {"REFUND_FAILED", "GATEWAY_DOWN"}:
            refund.status = PaymentState.REFUND_FAILED.value
            target_state = PaymentState.REFUND_FAILED

        else:
            refund.status = PaymentState.UNKNOWN.value
            target_state = PaymentState.UNKNOWN

        PaymentStateMachine.validate(current_state, target_state)

        transaction.status = target_state.value

        await create_state_log(
            db,
            transaction,
            current_state.value,
            target_state.value,
            f"Refund gateway result: {gateway_status}",
        )

        await db.commit()
        await db.refresh(refund)

        return refund


@router.post(
    "",
    response_model=RefundResponse,
    status_code=201,
)
async def create_refund(
    refund_data: RefundCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    mock_response: MockOutcome = Header(
        default="success",
        alias="X-Mock-Response",
    ),
    mock_delay_ms: int = Header(
        default=50,
        alias="X-Mock-Delay-Ms",
        ge=0,
        le=10000,
    ),
    mock_gateway_down: bool = Header(
        default=False,
        alias="X-Mock-Gateway-Down",
    ),
):
    """Create a safe, idempotent refund."""

    try:
        transaction_id = UUID(refund_data.transaction_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid transaction ID.",
        ) from exc

    # Step 1: Check whether this refund request already exists.
    existing = await find_existing_refund(
        db,
        transaction_id,
        refund_data.idempotency_key,
        refund_data.amount,
    )

    if existing is not None:
        response.status_code = 200
        return to_refund_response(existing)

    # Step 2: Lock and validate the original transaction.
    transaction = await get_refundable_transaction(
        db,
        transaction_id,
        refund_data.merchant_id,
    )

    if transaction.gateway_name is None:
        raise HTTPException(
            status_code=409,
            detail="Transaction has no associated payment gateway.",
        )

    # Step 3: Calculate already refunded and pending amounts.
    reserved_amount = await calculate_reserved_refund_amount(
        db,
        transaction_id,
    )

    available_amount = transaction.amount - reserved_amount

    if refund_data.amount > available_amount:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Refund amount exceeds the available refundable balance."
                ),
                "original_amount": transaction.amount,
                "already_refunded_or_reserved": reserved_amount,
                "available_amount": available_amount,
            },
        )

    # Step 4: Reserve the refund before calling the gateway.
    refund = Refund(
        transaction_id=transaction.id,
        idempotency_key=refund_data.idempotency_key,
        amount=refund_data.amount,
        currency=transaction.currency,
        status=PaymentState.REFUND_INITIATED.value,
        gateway_name=transaction.gateway_name,
    )

    previous_state = transaction.status
    target_state = PaymentState.REFUND_INITIATED

    PaymentStateMachine.validate(
        PaymentState(previous_state),
        target_state,
    )

    transaction.status = target_state.value
    db.add(refund)

    await create_state_log(
        db,
        transaction,
        previous_state,
        target_state.value,
        "Refund request initiated.",
    )

    try:
        await db.commit()
        await db.refresh(refund)

    except IntegrityError as exc:
        await db.rollback()

        # Another identical request may have created the refund first.
        existing = await find_existing_refund(
            db,
            transaction_id,
            refund_data.idempotency_key,
            refund_data.amount,
        )

        if existing is not None:
            response.status_code = 200
            return to_refund_response(existing)

        raise HTTPException(
            status_code=409,
            detail="Could not create refund because of a database conflict.",
        ) from exc

    # Step 5: Call the gateway only after the reservation is committed.
    try:
        gateway_result = await process_mock_refund(
            gateway_name=refund.gateway_name,
            amount=refund.amount,
            outcome=mock_response,
            delay_ms=mock_delay_ms,
            gateway_down=mock_gateway_down,
        )

    except Exception:
        # A gateway exception does not prove that the refund failed.
        await mark_refund_unknown(refund.id)

        async with AsyncSessionLocal() as read_db:
            result = await read_db.execute(
                select(Refund).where(Refund.id == refund.id)
            )
            updated_refund = result.scalar_one()

            response.status_code = 202
            return to_refund_response(updated_refund)

    # Step 6: Save the gateway result.
    updated_refund = await finalize_refund(
        refund.id,
        gateway_result.status,
    )

    if updated_refund.status == PaymentState.UNKNOWN.value:
        response.status_code = 202
    elif updated_refund.status == PaymentState.REFUND_FAILED.value:
        response.status_code = 200

    return to_refund_response(updated_refund)


# --------------------------------------------------
# GET: List refunds belonging to a merchant
# --------------------------------------------------

@router.get(
    "",
    response_model=list[RefundResponse],
)
async def list_refunds(
    merchant_id: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List refunds belonging to a merchant with pagination."""

    result = await db.execute(
        select(Refund)
        .join(Transaction, Refund.transaction_id == Transaction.id)
        .where(Transaction.merchant_id == merchant_id)
        .order_by(Refund.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    refunds = result.scalars().all()

    return [
        to_refund_response(refund)
        for refund in refunds
    ]


# --------------------------------------------------
# GET: Retrieve one refund by ID
# --------------------------------------------------

@router.get(
    "/{refund_id}",
    response_model=RefundResponse,
)
async def get_refund(
    refund_id: UUID,
    merchant_id: str = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a refund belonging to a merchant."""

    result = await db.execute(
        select(Refund)
        .join(Transaction, Refund.transaction_id == Transaction.id)
        .where(
            Refund.id == refund_id,
            Transaction.merchant_id == merchant_id,
        )
    )

    refund = result.scalar_one_or_none()

    if refund is None:
        raise HTTPException(
            status_code=404,
            detail="Refund not found.",
        )

    return to_refund_response(refund)

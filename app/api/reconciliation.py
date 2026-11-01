
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.domain.state_machine import (
    InvalidStateTransition,
    PaymentState,
    PaymentStateMachine,
)
from app.models.reconciliation_log import ReconciliationLog
from app.models.transaction import Transaction
from app.models.transaction_state_log import TransactionStateLog
from app.services.payment_service import fetch_mock_transaction_status


router = APIRouter(
    prefix="/api/v1/reconciliation",
    tags=["Reconciliation"],
)


def reconciliation_response(log: ReconciliationLog) -> dict:
    return {
        "id": str(log.id),
        "transaction_id": str(log.transaction_id),
        "gateway_name": log.gateway_name,
        "previous_status": log.previous_status,
        "reconciled_status": log.reconciled_status,
        "result": log.result,
        "details": log.details,
        "created_at": log.created_at,
    }


@router.post("/{transaction_id}")
async def reconcile_transaction(
    transaction_id: UUID,
    db: AsyncSession = Depends(get_db),
    mock_outcome: Literal["success", "failure", "timeout", "error"] = Header(
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
    # Step 1: Read the transaction without locking it.
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found.",
        )

    if not transaction.gateway_name:
        raise HTTPException(
            status_code=400,
            detail="Transaction has no assigned gateway.",
        )

    gateway_name = transaction.gateway_name

    # Release the database transaction before the gateway call.
    await db.commit()

    # Step 2: Perform a read-only gateway status lookup.
    gateway_result = await fetch_mock_transaction_status(
        gateway_name=gateway_name,
        transaction_id=str(transaction_id),
        outcome=mock_outcome,
        delay_ms=mock_delay_ms,
        gateway_down=mock_gateway_down,
    )

    # Step 3: Reopen a short database transaction and lock the record.
    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .with_for_update()
    )
    transaction = result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found.",
        )

    previous_status = transaction.status
    reconciled_status = previous_status
    reconciliation_result = "NO_CHANGE"

    details = gateway_result.message

    # Step 4: Interpret the gateway response.
    if gateway_result.status in ("UNKNOWN", "GATEWAY_DOWN", "ERROR"):
        reconciliation_result = gateway_result.status

    elif gateway_result.status in ("CAPTURED", "FAILED"):
        target_state = PaymentState(gateway_result.status)

        try:
            current_state = PaymentState(previous_status)

            if current_state == target_state:
                reconciliation_result = "ALREADY_MATCHED"

            else:
                try:
                    PaymentStateMachine.validate(
                        current_state,
                        target_state,
                    )

                    PaymentStateMachine.transition(
                        current_state,
                        target_state,
                    )

                    transaction.status = target_state.value
                    reconciled_status = target_state.value

                    db.add(
                        TransactionStateLog(
                            transaction_id=transaction.id,
                            previous_state=previous_status,
                            new_state=target_state.value,
                            reason="Gateway status reconciliation",
                        )
                    )

                    reconciliation_result = "RECONCILED"

                except InvalidStateTransition:
                    # A conflicting definitive gateway response must
                    # not silently overwrite an existing payment state.
                    reconciliation_result = "MISMATCH"

                    try:
                        mismatch_state = PaymentState.RECONCILIATION_MISMATCH

                        PaymentStateMachine.validate(
                            current_state,
                            mismatch_state,
                        )

                        transaction.status = mismatch_state.value
                        reconciled_status = mismatch_state.value

                        db.add(
                            TransactionStateLog(
                                transaction_id=transaction.id,
                                previous_state=previous_status,
                                new_state=mismatch_state.value,
                                reason="Gateway and local payment statuses conflict",
                            )
                        )

                    except InvalidStateTransition:
                        pass

        except ValueError:
            reconciliation_result = "MISMATCH"

    else:
        reconciliation_result = "ERROR"
        details = "Unexpected gateway status received."

    # Step 5: Record every reconciliation attempt.
    reconciliation_log = ReconciliationLog(
        transaction_id=transaction.id,
        gateway_name=gateway_name,
        previous_status=previous_status,
        reconciled_status=reconciled_status,
        result=reconciliation_result,
        details=json.dumps(
            {
                "gateway_status": gateway_result.status,
                "gateway_message": gateway_result.message,
                "gateway_latency_ms": gateway_result.latency_ms,
            }
        ),
    )

    db.add(reconciliation_log)
    await db.commit()
    await db.refresh(reconciliation_log)

    return {
        "transaction_id": str(transaction.id),
        "gateway_name": gateway_name,
        "previous_status": previous_status,
        "current_status": reconciled_status,
        "gateway_status": gateway_result.status,
        "result": reconciliation_result,
        "message": details,
        "gateway_latency_ms": gateway_result.latency_ms,
        "reconciliation": reconciliation_response(reconciliation_log),
    }


@router.get("")
async def list_reconciliation_records(
    transaction_id: UUID | None = Query(default=None),
    gateway_name: str | None = Query(default=None),
    reconciliation_result: str | None = Query(
        default=None,
        alias="result",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    statement = select(ReconciliationLog)

    if transaction_id is not None:
        statement = statement.where(
            ReconciliationLog.transaction_id == transaction_id
        )

    if gateway_name is not None:
        statement = statement.where(
            ReconciliationLog.gateway_name == gateway_name
        )

    if reconciliation_result is not None:
        statement = statement.where(
            ReconciliationLog.result == reconciliation_result
        )

    statement = (
        statement
        .order_by(ReconciliationLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(statement)
    records = result.scalars().all()

    return {
        "count": len(records),
        "limit": limit,
        "offset": offset,
        "items": [
            reconciliation_response(record)
            for record in records
        ],
    }


@router.get("/{transaction_id}/history")
async def get_reconciliation_history(
    transaction_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction.id).where(Transaction.id == transaction_id)
    )

    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found.",
        )

    result = await db.execute(
        select(ReconciliationLog)
        .where(ReconciliationLog.transaction_id == transaction_id)
        .order_by(ReconciliationLog.created_at.desc())
    )

    records = result.scalars().all()

    return {
        "transaction_id": str(transaction_id),
        "count": len(records),
        "items": [
            reconciliation_response(record)
            for record in records
        ],
    }

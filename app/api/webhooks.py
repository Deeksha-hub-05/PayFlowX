
import hashlib
import hmac
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import WebhookEvent
from app.config import settings
from app.database import get_db
from app.domain.state_machine import (
    InvalidStateTransition,
    PaymentState,
    PaymentStateMachine,
)
from app.models.processed_webhook_event import ProcessedWebhookEvent
from app.models.reconciliation_log import ReconciliationLog
from app.models.transaction import Transaction
from app.models.transaction_state_log import TransactionStateLog

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


EVENT_TARGET_STATES = {
    "payment.authorized": PaymentState.AUTHORISED,
    "payment.failed": PaymentState.AUTH_FAILED,
    "payment.captured": PaymentState.CAPTURED,
}


WEBHOOK_SECRETS = {
    "Razorpay": settings.razorpay_webhook_secret,
    "Stripe": settings.stripe_webhook_secret,
    "PayU": settings.payu_webhook_secret,
}


def verify_webhook_signature(
    gateway_name: str,
    payload: bytes,
    signature: str | None,
) -> bool:
    secret = WEBHOOK_SECRETS.get(gateway_name)

    if not secret or not signature:
        return False

    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


@router.post("/{gateway_name}")
async def receive_webhook(
    gateway_name: str,
    request: Request,
    event: WebhookEvent,
    x_webhook_signature: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    if gateway_name != event.gateway_name:
        raise HTTPException(status_code=400, detail="Gateway name mismatch.")

    if gateway_name not in WEBHOOK_SECRETS:
        raise HTTPException(status_code=400, detail="Unsupported gateway.")

    raw_body = await request.body()

    if not verify_webhook_signature(
        gateway_name,
        raw_body,
        x_webhook_signature,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing webhook signature.",
        )

    target_state = EVENT_TARGET_STATES[event.event_type]

    if event.status != target_state.value:
        raise HTTPException(status_code=400, detail="Event type and status mismatch.")

    try:
        transaction_id = uuid.UUID(event.transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid transaction ID.") from exc

    existing_event = await db.execute(
        select(ProcessedWebhookEvent).where(
            ProcessedWebhookEvent.gateway_name == gateway_name,
            ProcessedWebhookEvent.event_id == event.event_id,
        )
    )

    if existing_event.scalar_one_or_none() is not None:
        return {
            "status": "duplicate_ignored",
            "event_id": event.event_id,
        }

    transaction_result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .with_for_update()
    )
    transaction = transaction_result.scalar_one_or_none()

    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    if transaction.gateway_name != gateway_name:
        raise HTTPException(
            status_code=400,
            detail="Webhook gateway does not match the transaction gateway.",
        )

    current_state = PaymentState(transaction.status)

    try:
        PaymentStateMachine.validate(current_state, target_state)
    except InvalidStateTransition as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid payment state transition: {exc}",
        ) from exc

    now = datetime.now(timezone.utc)

    db.add(
        ProcessedWebhookEvent(
            gateway_name=gateway_name,
            event_id=event.event_id,
            event_type=event.event_type,
            processing_status="PROCESSED",
            received_at=now,
            processed_at=now,
        )
    )

    transaction.status = target_state.value

    db.add(
        TransactionStateLog(
            transaction_id=transaction.id,
            previous_state=current_state.value,
            new_state=target_state.value,
            reason=f"Webhook {event.event_id}: {event.event_type}",
        )
    )

    db.add(
        ReconciliationLog(
            transaction_id=transaction.id,
            gateway_name=gateway_name,
            previous_status=current_state.value,
            reconciled_status=target_state.value,
            result="APPLIED",
            details=f"Webhook event {event.event_id} processed.",
        )
    )

    try:
        await db.commit()

    except IntegrityError:
        await db.rollback()

        duplicate_check = await db.execute(
            select(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.gateway_name == gateway_name,
                ProcessedWebhookEvent.event_id == event.event_id,
            )
        )

        if duplicate_check.scalar_one_or_none() is not None:
            return {
                "status": "duplicate_ignored",
                "event_id": event.event_id,
            }

        raise

    return {
        "status": "processed",
        "event_id": event.event_id,
        "transaction_id": str(transaction.id),
        "payment_status": target_state.value,
    }

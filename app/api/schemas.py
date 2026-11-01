
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=100)
    amount: int = Field(gt=0, description="Amount in the smallest currency unit")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_method: Literal["UPI", "CARD", "NETBANKING", "WALLET"]
    idempotency_key: str = Field(min_length=1, max_length=255)


class PaymentResponse(BaseModel):
    id: str
    merchant_id: str
    amount: int
    currency: str
    payment_method: str
    status: str

class WebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_name: Literal["Razorpay", "Stripe", "PayU"]
    event_id: str = Field(min_length=1, max_length=255)
    event_type: Literal["payment.authorized", "payment.failed", "payment.captured"]
    transaction_id: str = Field(min_length=1, max_length=36)
    status: Literal["AUTHORISED", "AUTH_FAILED", "CAPTURED", "FAILED"]



class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=36)
    amount: int = Field(gt=0, description="Refund amount in the smallest currency unit")
    idempotency_key: str = Field(min_length=1, max_length=255)


class RefundResponse(BaseModel):
    id: str
    transaction_id: str
    amount: int
    currency: str
    status: str
    gateway_name: str
    gateway_refund_id: str | None = None
    

class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=100)
    transaction_id: str = Field(min_length=1, max_length=36)
    amount: int = Field(
        gt=0,
        description="Refund amount in the smallest currency unit",
    )
    idempotency_key: str = Field(min_length=1, max_length=255)

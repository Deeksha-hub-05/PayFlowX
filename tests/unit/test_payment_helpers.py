from app.api.payments import make_request_hash
from app.api.schemas import PaymentCreate


def make_payment(
    amount: int = 42000,
    idempotency_key: str = "test-key-001",
) -> PaymentCreate:
    return PaymentCreate(
        merchant_id="merchant_test_001",
        amount=amount,
        currency="INR",
        payment_method="UPI",
        idempotency_key=idempotency_key,
    )


def test_same_payment_details_produce_same_hash():
    first = make_payment(idempotency_key="key-one")
    second = make_payment(idempotency_key="key-two")

    assert make_request_hash(first) == make_request_hash(second)


def test_different_amount_produces_different_hash():
    first = make_payment(amount=42000)
    second = make_payment(amount=43000)

    assert make_request_hash(first) != make_request_hash(second)
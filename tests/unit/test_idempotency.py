
from app.api.payments import make_request_hash
from app.api.schemas import PaymentCreate


def make_payment(
    amount: int = 10000,
    idempotency_key: str = "idem-check-001",
) -> PaymentCreate:
    return PaymentCreate(
        merchant_id="merchant_test",
        amount=amount,
        currency="INR",
        payment_method="UPI",
        idempotency_key=idempotency_key,
    )


def test_same_payment_details_produce_same_hash():
    payment_one = make_payment()
    payment_two = make_payment()

    assert make_request_hash(payment_one) == make_request_hash(payment_two)


def test_different_amount_produces_different_hash():
    payment_one = make_payment(amount=10000)
    payment_two = make_payment(amount=12000)

    assert make_request_hash(payment_one) != make_request_hash(payment_two)


def test_idempotency_key_does_not_change_request_hash():
    payment_one = make_payment(idempotency_key="key-one")
    payment_two = make_payment(idempotency_key="key-two")

    assert make_request_hash(payment_one) == make_request_hash(payment_two)

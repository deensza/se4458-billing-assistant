"""Pay Bill: POST /api/v1/payments (auth, simulated payment)."""

from sqlalchemy import func, select

from app.models import Payment

URL = "/api/v1/payments"
BASE = {"subscriberNo": "5551001", "month": 10, "year": 2026}


def pay(client, headers, amount, txn):
    return client.post(URL, json={**BASE, "amount": amount, "transactionId": txn}, headers=headers)


def test_partial_payment(client, calculated_bill, user1001_headers):
    r = pay(client, user1001_headers, 30, "TXN-1")
    assert r.status_code == 201
    body = r.json()
    assert body["paymentStatus"] == "SUCCESS"
    assert (body["paidAmount"], body["totalPaid"], body["remainingBalance"]) == (30.0, 30.0, 50.0)
    assert body["billStatus"] == "PARTIALLY_PAID"


def test_full_payment_in_two_steps_marks_paid(client, calculated_bill, user1001_headers):
    pay(client, user1001_headers, 30, "TXN-1")
    body = pay(client, user1001_headers, 50, "TXN-2").json()
    assert (body["totalPaid"], body["remainingBalance"], body["billStatus"]) == (80.0, 0.0, "PAID")


def test_decimal_amounts_are_exact(client, calculated_bill, user1001_headers):
    pay(client, user1001_headers, 0.1, "TXN-D1")
    body = pay(client, user1001_headers, 0.2, "TXN-D2").json()
    assert body["totalPaid"] == 0.3
    assert body["remainingBalance"] == 79.7


def test_duplicate_transaction_id_is_rejected(client, calculated_bill, user1001_headers, db):
    assert pay(client, user1001_headers, 10, "TXN-DUP").status_code == 201
    r = pay(client, user1001_headers, 10, "TXN-DUP")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DUPLICATE_TRANSACTION"
    assert db.scalar(select(func.count()).select_from(Payment)) == 1
    assert client.get("/api/v1/bills", params=BASE).json()["paidAmount"] == 10.0  # balance preserved


def test_amount_exceeding_balance_is_rejected(client, calculated_bill, user1001_headers):
    r = pay(client, user1001_headers, 80.01, "TXN-BIG")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AMOUNT_EXCEEDS_BALANCE"
    assert r.json()["error"]["details"]["remainingBalance"] == 80.0
    assert client.get("/api/v1/bills", params=BASE).json()["paidAmount"] == 0.0


def test_paying_a_fully_paid_bill_is_409(client, calculated_bill, user1001_headers):
    pay(client, user1001_headers, 80, "TXN-FULL")
    r = pay(client, user1001_headers, 1, "TXN-AFTER")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BILL_ALREADY_PAID"


def test_zero_negative_or_too_precise_amount_is_422(client, calculated_bill, user1001_headers):
    for amount in (0, -5, 10.123):
        r = pay(client, user1001_headers, amount, f"TXN-BAD-{amount}")
        assert r.status_code == 422, amount
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_transaction_id_is_422(client, calculated_bill, user1001_headers):
    r = client.post(URL, json={**BASE, "amount": 10}, headers=user1001_headers)
    assert r.status_code == 422


def test_paying_another_subscribers_bill_is_403(client, calculated_bill, user1002_headers):
    r = pay(client, user1002_headers, 10, "TXN-OTHER")
    assert r.status_code == 403


def test_pay_requires_token(client, calculated_bill):
    assert client.post(URL, json={**BASE, "amount": 10, "transactionId": "T"}).status_code == 401


def test_pay_bill_not_calculated_is_404(client, user1001_headers):
    r = client.post(URL, json={**BASE, "month": 9, "amount": 10, "transactionId": "TXN-404"}, headers=user1001_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "BILL_NOT_FOUND"

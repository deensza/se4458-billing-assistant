"""Query Bill: GET /api/v1/bills (public, no authentication, no paging)."""

URL = "/api/v1/bills"
PARAMS = {"subscriberNo": "5551001", "month": 10, "year": 2026}


def test_query_bill_returns_total_paid_remaining_status(client, calculated_bill):
    r = client.get(URL, params=PARAMS)  # no Authorization header: public operation
    assert r.status_code == 200
    body = r.json()
    assert body["billTotal"] == 80.0
    assert body["paidAmount"] == 0.0
    assert body["remainingBalance"] == 80.0
    assert body["status"] == "UNPAID"
    assert body["dueDate"] == "2026-11-15"


def test_query_bill_reflects_partial_payment(client, calculated_bill, user1001_headers):
    client.post(
        "/api/v1/payments", json={**PARAMS, "amount": 25.5, "transactionId": "T-Q-1"}, headers=user1001_headers
    )
    body = client.get(URL, params=PARAMS).json()
    assert (body["paidAmount"], body["remainingBalance"], body["status"]) == (25.5, 54.5, "PARTIALLY_PAID")


def test_query_bill_not_calculated_is_404(client):
    r = client.get(URL, params={**PARAMS, "month": 9})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "BILL_NOT_FOUND"


def test_query_bill_unknown_subscriber_is_404(client):
    r = client.get(URL, params={**PARAMS, "subscriberNo": "1111111"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SUBSCRIBER_NOT_FOUND"


def test_query_bill_missing_or_invalid_params_is_422(client):
    assert client.get(URL, params={"subscriberNo": "5551001"}).status_code == 422
    assert client.get(URL, params={**PARAMS, "subscriberNo": "ABC"}).status_code == 422

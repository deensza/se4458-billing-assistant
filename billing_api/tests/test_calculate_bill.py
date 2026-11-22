"""Calculate Bill: POST /api/v1/bills/calculate (ADMIN)."""

URL = "/api/v1/bills/calculate"
BODY = {"subscriberNo": "5551001", "month": 10, "year": 2026}


def test_calculate_worked_example_is_80(calculated_bill):
    assert calculated_bill["billTotal"] == 80.0
    assert calculated_bill["paidAmount"] == 0.0
    assert calculated_bill["remainingBalance"] == 80.0
    assert calculated_bill["status"] == "UNPAID"
    assert calculated_bill["dueDate"] == "2026-11-15"


def test_calculate_with_no_usage_is_internet_base_50(client, admin_headers):
    r = client.post(URL, json=BODY, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["action"] == "CREATED"
    assert r.json()["bill"]["billTotal"] == 50.0


def test_partial_blocks_are_charged_as_full_blocks(client, admin_headers, add_usage_events):
    add_usage_events("5551003", 2026, 10, minutes=1_010, internet_mb=20_001)
    r = client.post(URL, json={"subscriberNo": "5551003", "month": 10, "year": 2026}, headers=admin_headers)
    assert r.json()["bill"]["billTotal"] == 70.0  # $10 phone + $60 internet


def test_usage_via_api_is_included(client, admin_headers):
    for usage_type in ("PHONE", "INTERNET"):
        client.post("/api/v1/usage", json={**BODY, "usageType": usage_type}, headers=admin_headers)
    r = client.post(URL, json=BODY, headers=admin_headers)
    assert r.json()["bill"]["billTotal"] == 50.0  # 10 minutes and 1 MB are within the allowance


def test_recalculation_updates_total_and_keeps_payments(client, admin_headers, user1001_headers, add_usage_events):
    add_usage_events("5551001", 2026, 10, minutes=1_350, internet_mb=35_000)
    client.post(URL, json=BODY, headers=admin_headers)
    client.post(
        "/api/v1/payments", json={**BODY, "amount": 30, "transactionId": "T-RECALC-1"}, headers=user1001_headers
    )
    add_usage_events("5551001", 2026, 10, minutes=700)  # 2,050 minutes -> $20 phone
    r = client.post(URL, json=BODY, headers=admin_headers)
    bill = r.json()["bill"]
    assert r.json()["action"] == "RECALCULATED"
    assert (bill["billTotal"], bill["paidAmount"], bill["remainingBalance"]) == (90.0, 30.0, 60.0)
    assert bill["status"] == "PARTIALLY_PAID"


def test_calculate_unknown_subscriber_is_404(client, admin_headers):
    r = client.post(URL, json={**BODY, "subscriberNo": "1234567"}, headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SUBSCRIBER_NOT_FOUND"


def test_calculate_invalid_month_is_422(client, admin_headers):
    r = client.post(URL, json={**BODY, "month": 0}, headers=admin_headers)
    assert r.status_code == 422


def test_subscriber_can_calculate_own_bill(client, user1001_headers):
    r = client.post(URL, json=BODY, headers=user1001_headers)
    assert r.status_code == 200
    assert r.json()["transactionStatus"] == "SUCCESS"


def test_calculate_other_account_is_403_and_requires_token(client, user1002_headers):
    assert client.post(URL, json=BODY, headers=user1002_headers).status_code == 403
    assert client.post(URL, json=BODY).status_code == 401

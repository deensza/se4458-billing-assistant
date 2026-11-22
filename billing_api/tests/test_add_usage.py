"""Add Usage: POST /api/v1/usage (ADMIN)."""

from sqlalchemy import func, select

from app.models import UsageRecord

URL = "/api/v1/usage"


def test_add_phone_usage_adds_10_minutes(client, admin_headers, db):
    r = client.post(
        URL, json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "PHONE"}, headers=admin_headers
    )
    assert r.status_code == 201
    body = r.json()
    assert body["transactionStatus"] == "SUCCESS"
    assert body["quantityAdded"] == 10
    assert body["unit"] == "MINUTES"
    assert db.scalar(select(func.sum(UsageRecord.quantity))) == 10


def test_add_internet_usage_adds_1_mb(client, admin_headers):
    r = client.post(
        URL,
        json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "INTERNET"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert (r.json()["quantityAdded"], r.json()["unit"]) == (1, "MB")


def test_repeated_events_accumulate(client, admin_headers, db):
    for _ in range(3):
        client.post(
            URL,
            json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "PHONE"},
            headers=admin_headers,
        )
    assert db.scalar(select(func.sum(UsageRecord.quantity))) == 30


def test_add_usage_unknown_subscriber_is_404(client, admin_headers):
    r = client.post(
        URL, json={"subscriberNo": "9999999", "month": 10, "year": 2026, "usageType": "PHONE"}, headers=admin_headers
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "SUBSCRIBER_NOT_FOUND"


def test_add_usage_invalid_type_and_month_is_422(client, admin_headers):
    r = client.post(
        URL, json={"subscriberNo": "5551001", "month": 13, "year": 2026, "usageType": "SMS"}, headers=admin_headers
    )
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"body.month", "body.usageType"} <= fields


def test_spec_spelling_phone_and_internet_is_accepted(client, admin_headers):
    """The specification writes the usage types as "Phone" and "Internet"."""
    for usage_type, unit in (("Phone", "MINUTES"), ("Internet", "MB"), ("internet", "MB")):
        r = client.post(
            URL, json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": usage_type}, headers=admin_headers
        )
        assert r.status_code == 201, usage_type
        assert r.json()["unit"] == unit


def test_subscriber_can_add_usage_to_own_account(client, user1001_headers):
    r = client.post(
        URL, json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "PHONE"}, headers=user1001_headers
    )
    assert r.status_code == 201


def test_subscriber_cannot_add_usage_to_another_account(client, user1001_headers):
    r = client.post(
        URL, json={"subscriberNo": "5551002", "month": 10, "year": 2026, "usageType": "PHONE"}, headers=user1001_headers
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_add_usage_requires_token(client):
    r = client.post(URL, json={"subscriberNo": "5551001", "month": 10, "year": 2026, "usageType": "PHONE"})
    assert r.status_code == 401

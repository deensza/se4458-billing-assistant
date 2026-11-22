"""Origin protection: with GATEWAY_SHARED_SECRET set, only requests forwarded by the gateway are accepted."""

import pytest

from app.config import settings

PARAMS = {"subscriberNo": "5551001", "month": 10, "year": 2026}


@pytest.fixture
def gateway_secret(monkeypatch):
    monkeypatch.setattr(settings, "gateway_shared_secret", "s3cret-from-kong")
    return "s3cret-from-kong"


def test_request_with_gateway_header_is_accepted(client, calculated_bill, gateway_secret):
    r = client.get("/api/v1/bills", params=PARAMS, headers={"X-Gateway-Secret": gateway_secret})
    assert r.status_code == 200


def test_direct_request_without_gateway_header_is_403(client, calculated_bill, gateway_secret):
    r = client.get("/api/v1/bills", params=PARAMS)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "GATEWAY_REQUIRED"


def test_wrong_gateway_header_is_403(client, calculated_bill, gateway_secret):
    r = client.get("/api/v1/bills", params=PARAMS, headers={"X-Gateway-Secret": "guess"})
    assert r.status_code == 403


def test_health_is_open_for_platform_probes(client, gateway_secret):
    assert client.get("/health").status_code == 200

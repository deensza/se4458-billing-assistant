"""Query Bill Detailed: GET /api/v1/bills/detailed (auth + paging)."""

URL = "/api/v1/bills/detailed"
PARAMS = {"subscriberNo": "5551001", "month": 10, "year": 2026}


def test_detailed_breakdown(client, calculated_bill, user1001_headers):
    r = client.get(URL, params=PARAMS, headers=user1001_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["billTotal"] == 80.0
    assert body["phone"] == {
        "minutes": 1350,
        "includedMinutes": 1000,
        "extraBlocks": 1,
        "blockSizeMinutes": 1000,
        "blockPrice": 10.0,
        "charge": 10.0,
    }
    assert body["internet"]["usageMb"] == 35000
    assert body["internet"]["usageGb"] == 35.0
    assert body["internet"]["extraBlocks"] == 2
    assert body["internet"]["charge"] == 70.0
    assert body["recalculationNeeded"] is False


def test_detailed_paging(client, calculated_bill, user1001_headers):
    # 135 phone events + 35,000 internet events
    r = client.get(URL, params={**PARAMS, "page": 2, "pageSize": 50}, headers=user1001_headers)
    paged = r.json()["usageRecords"]
    assert (paged["page"], paged["pageSize"], paged["totalItems"]) == (2, 50, 35_135)
    assert paged["totalPages"] == 703
    assert len(paged["items"]) == 50

    last = client.get(URL, params={**PARAMS, "page": 703, "pageSize": 50}, headers=user1001_headers).json()
    assert len(last["usageRecords"]["items"]) == 35


def test_detailed_page_beyond_last_is_empty(client, calculated_bill, user1001_headers):
    r = client.get(URL, params={**PARAMS, "page": 10_000, "pageSize": 100}, headers=user1001_headers)
    assert r.status_code == 200
    assert r.json()["usageRecords"]["items"] == []


def test_detailed_invalid_paging_is_422(client, user1001_headers):
    assert client.get(URL, params={**PARAMS, "page": 0}, headers=user1001_headers).status_code == 422
    assert client.get(URL, params={**PARAMS, "pageSize": 101}, headers=user1001_headers).status_code == 422


def test_detailed_flags_usage_added_after_calculation(client, calculated_bill, admin_headers, user1001_headers):
    client.post("/api/v1/usage", json={**PARAMS, "usageType": "PHONE"}, headers=admin_headers)
    assert client.get(URL, params=PARAMS, headers=user1001_headers).json()["recalculationNeeded"] is True


def test_detailed_other_subscriber_is_403(client, calculated_bill, user1002_headers):
    """User 1002 must not read 5551001's private data even if they know the number."""
    r = client.get(URL, params=PARAMS, headers=user1002_headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_detailed_admin_can_read_any_account(client, calculated_bill, admin_headers):
    assert client.get(URL, params=PARAMS, headers=admin_headers).status_code == 200


def test_detailed_requires_token(client, calculated_bill):
    assert client.get(URL, params=PARAMS).status_code == 401


def test_detailed_bill_not_calculated_is_404(client, user1001_headers):
    r = client.get(URL, params={**PARAMS, "month": 9}, headers=user1001_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "BILL_NOT_FOUND"

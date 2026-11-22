"""POST /api/v1/auth/token and token validation."""


def test_login_success_returns_jwt(client):
    r = client.post("/api/v1/auth/token", json={"username": "user1001", "password": "Pass1001!"})
    assert r.status_code == 200
    body = r.json()
    assert body["tokenType"] == "Bearer"
    assert body["role"] == "SUBSCRIBER"
    assert body["subscriberNo"] == "5551001"
    assert body["expiresIn"] == 3600
    assert body["accessToken"].count(".") == 2


def test_login_wrong_password_is_401(client):
    r = client.post("/api/v1/auth/token", json={"username": "user1001", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_user_is_401(client):
    r = client.post("/api/v1/auth/token", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_missing_fields_is_422(client):
    r = client.post("/api/v1/auth/token", json={"username": "user1001"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_protected_route_without_token_is_401(client):
    r = client.get("/api/v1/bills/detailed", params={"subscriberNo": "5551001", "month": 10, "year": 2026})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_tampered_token_is_401(client, user1001_headers):
    headers = {"Authorization": user1001_headers["Authorization"][:-3] + "abc"}
    r = client.get(
        "/api/v1/bills/detailed", params={"subscriberNo": "5551001", "month": 10, "year": 2026}, headers=headers
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_token_is_401(client, expired_headers):
    r = client.get(
        "/api/v1/bills/detailed",
        params={"subscriberNo": "5551001", "month": 10, "year": 2026},
        headers=expired_headers,
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_login_token_works_on_protected_route(client, calculated_bill):
    token = client.post("/api/v1/auth/token", json={"username": "user1001", "password": "Pass1001!"}).json()[
        "accessToken"
    ]
    r = client.get(
        "/api/v1/bills/detailed",
        params={"subscriberNo": "5551001", "month": 10, "year": 2026},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

"""Test fixtures.

The unit tests need no cloud, no gateway and no LLM. By default they run against an in-memory
SQLite database created fresh for every test (fast, zero setup). The *application* itself uses
PostgreSQL; to run the same tests against PostgreSQL set TEST_DATABASE_URL, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://billing:billing@localhost:5432/billing_test pytest
"""

import os

os.environ.setdefault("JWT_SECRET", "unit-test-secret-0123456789abcdef0123456789")
os.environ.setdefault("BCRYPT_ROUNDS", "4")
os.environ.setdefault("INIT_DB_ON_STARTUP", "false")

from datetime import datetime, timedelta, timezone  # noqa: E402

import jwt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, insert  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Subscriber, UsageRecord, UsageType, User, UserRole  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")


@pytest.fixture
def engine():
    if TEST_DATABASE_URL.startswith("sqlite"):
        eng = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def seeded(db):
    """Three subscribers, one admin and two subscriber users."""
    db.add_all([Subscriber(subscriber_no=n, full_name=f"Test {n}") for n in ("5551001", "5551002", "5551003")])
    db.flush()
    db.add_all(
        [
            User(username="admin", password_hash=hash_password("Admin123!"), role=UserRole.ADMIN),
            User(
                username="user1001",
                password_hash=hash_password("Pass1001!"),
                role=UserRole.SUBSCRIBER,
                subscriber_no="5551001",
            ),
            User(
                username="user1002",
                password_hash=hash_password("Pass1002!"),
                role=UserRole.SUBSCRIBER,
                subscriber_no="5551002",
            ),
        ]
    )
    db.commit()
    return db


@pytest.fixture
def client(session_factory, seeded):
    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    return _auth(create_access_token("admin", UserRole.ADMIN, None))


@pytest.fixture
def user1001_headers():
    return _auth(create_access_token("user1001", UserRole.SUBSCRIBER, "5551001"))


@pytest.fixture
def user1002_headers():
    return _auth(create_access_token("user1002", UserRole.SUBSCRIBER, "5551002"))


@pytest.fixture
def expired_headers():
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token = jwt.encode(
        {
            "sub": "user1001",
            "role": "SUBSCRIBER",
            "subscriberNo": "5551001",
            "iss": settings.jwt_issuer,
            "iat": int(past.timestamp()),
            "exp": int((past + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return _auth(token)


@pytest.fixture
def add_usage_events(db):
    """Insert many Add Usage events directly (10 min / 1 MB each) to build realistic totals quickly."""

    def _add(subscriber_no: str, year: int, month: int, minutes: int = 0, internet_mb: int = 0):
        rows = [
            {"subscriber_no": subscriber_no, "year": year, "month": month, "usage_type": UsageType.PHONE, "quantity": 10}
            for _ in range(minutes // 10)
        ] + [
            {"subscriber_no": subscriber_no, "year": year, "month": month, "usage_type": UsageType.INTERNET, "quantity": 1}
            for _ in range(internet_mb)
        ]
        if rows:
            db.execute(insert(UsageRecord), rows)
            db.commit()

    return _add


@pytest.fixture
def calculated_bill(client, admin_headers, add_usage_events):
    """5551001, Oct 2026: 1,350 minutes + 35 GB -> $80 (guide section 4.3 worked example)."""
    add_usage_events("5551001", 2026, 10, minutes=1_350, internet_mb=35_000)
    r = client.post(
        "/api/v1/bills/calculate", json={"subscriberNo": "5551001", "month": 10, "year": 2026}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    return r.json()["bill"]

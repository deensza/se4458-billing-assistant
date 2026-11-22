"""Demo/test data. Loaded once at startup when SEED_DEMO_DATA=true (skipped if users already exist).

| Subscriber | User / password       | Data                                                                      |
|------------|-----------------------|---------------------------------------------------------------------------|
| -          | admin / Admin123!     | ADMIN role                                                                |
| 5551001    | user1001 / Pass1001!  | Sep 2026: 800 min, 18 GB -> $50 (PAID). Oct 2026: 1,350 min, 35 GB -> $80 (UNPAID) |
| 5551002    | user1002 / Pass1002!  | Oct 2026: 2,500 min, 12 GB -> $70, $30 paid (PARTIALLY_PAID)              |
| 5551003    | user1003 / Pass1003!  | Oct 2026: 1,010 min, 20,001 MB recorded, bill NOT calculated yet          |

Usage is stored as real Add Usage events (10 minutes or 1 MB each), exactly like the API creates them.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from . import pricing, services
from .models import Bill, Payment, Subscriber, UsageRecord, UsageType, User, UserRole
from .security import hash_password

logger = logging.getLogger("billing_api.seed")

SUBSCRIBERS = [
    ("5551001", "Demo Subscriber One"),
    ("5551002", "Demo Subscriber Two"),
    ("5551003", "Demo Subscriber Three"),
]
USERS = [
    ("admin", "Admin123!", UserRole.ADMIN, None),
    ("user1001", "Pass1001!", UserRole.SUBSCRIBER, "5551001"),
    ("user1002", "Pass1002!", UserRole.SUBSCRIBER, "5551002"),
    ("user1003", "Pass1003!", UserRole.SUBSCRIBER, "5551003"),
]
# (subscriber, year, month, phone_minutes, internet_mb, calculate_bill, payments[(txn, amount)])
USAGE_PLAN = [
    ("5551001", 2026, 9, 800, 18_000, True, [("SEED-TXN-0001", Decimal("50.00"))]),
    ("5551001", 2026, 10, 1_350, 35_000, True, []),
    ("5551002", 2026, 10, 2_500, 12_000, True, [("SEED-TXN-0002", Decimal("30.00"))]),
    ("5551003", 2026, 10, 1_010, 20_001, False, []),
]


def _usage_rows(subscriber_no: str, year: int, month: int, minutes: int, internet_mb: int) -> list[dict]:
    start = datetime(year, month, 1, 8, 0, tzinfo=timezone.utc)
    rows = []
    phone_events = minutes // pricing.PHONE_MINUTES_PER_EVENT
    for i in range(phone_events):
        rows.append(
            {
                "subscriber_no": subscriber_no,
                "year": year,
                "month": month,
                "usage_type": UsageType.PHONE,
                "quantity": pricing.PHONE_MINUTES_PER_EVENT,
                "recorded_at": start + timedelta(days=i % 28, minutes=i),
            }
        )
    for i in range(internet_mb // pricing.INTERNET_MB_PER_EVENT):
        rows.append(
            {
                "subscriber_no": subscriber_no,
                "year": year,
                "month": month,
                "usage_type": UsageType.INTERNET,
                "quantity": pricing.INTERNET_MB_PER_EVENT,
                "recorded_at": start + timedelta(days=i % 28, seconds=i),
            }
        )
    return rows


def seed_demo_data(db: Session) -> bool:
    if db.scalars(select(User.id).limit(1)).first() is not None:
        logger.info("Seed skipped: data already present.")
        return False

    for subscriber_no, name in SUBSCRIBERS:
        db.add(Subscriber(subscriber_no=subscriber_no, full_name=name))
    db.flush()
    for username, password, role, subscriber_no in USERS:
        db.add(User(username=username, password_hash=hash_password(password), role=role, subscriber_no=subscriber_no))
    for subscriber_no, year, month, minutes, internet_mb, _, _ in USAGE_PLAN:
        db.execute(insert(UsageRecord), _usage_rows(subscriber_no, year, month, minutes, internet_mb))
    db.commit()

    for subscriber_no, year, month, _, _, calculate, payments in USAGE_PLAN:
        if not calculate:
            continue
        services.calculate_bill(db, subscriber_no, year, month)
        bill = services.get_bill_or_404(db, subscriber_no, year, month)
        for transaction_id, amount in payments:
            bill.paid_amount += amount
            db.add(Payment(bill_id=bill.id, transaction_id=transaction_id, amount=amount, paid_by_username="seed"))
        bill.status = services.bill_status(bill.total_amount, bill.paid_amount)
        db.commit()
    logger.info("Demo data seeded.")
    return True

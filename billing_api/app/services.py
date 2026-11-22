"""Business logic for the billing operations (independent of HTTP)."""

import math
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import pricing
from .errors import ApiError
from .models import Bill, BillStatus, Payment, Subscriber, UsageRecord, UsageType, utcnow
from .security import CurrentUser, ensure_account_access

ZERO = Decimal("0.00")


# ---------- helpers ----------
def get_subscriber_or_404(db: Session, subscriber_no: str) -> Subscriber:
    subscriber = db.get(Subscriber, subscriber_no)
    if subscriber is None:
        raise ApiError(404, "SUBSCRIBER_NOT_FOUND", f"Subscriber {subscriber_no} was not found.")
    return subscriber


def get_bill_or_404(db: Session, subscriber_no: str, year: int, month: int, for_update: bool = False) -> Bill:
    stmt = select(Bill).where(
        Bill.subscriber_no == subscriber_no, Bill.year == year, Bill.month == month
    )
    if for_update:
        stmt = stmt.with_for_update()
    bill = db.scalars(stmt).first()
    if bill is None:
        raise ApiError(
            404,
            "BILL_NOT_FOUND",
            f"No calculated bill exists for subscriber {subscriber_no} for {year}-{month:02d}. "
            "Call Calculate Bill first.",
        )
    return bill


def bill_status(total: Decimal, paid: Decimal) -> BillStatus:
    if paid >= total:
        return BillStatus.PAID
    if paid > ZERO:
        return BillStatus.PARTIALLY_PAID
    return BillStatus.UNPAID


def remaining_balance(bill: Bill) -> Decimal:
    return max(ZERO, bill.total_amount - bill.paid_amount)


def usage_totals(db: Session, subscriber_no: str, year: int, month: int) -> tuple[int, int]:
    """Returns (phone_minutes, internet_mb) recorded for the period."""
    rows = db.execute(
        select(UsageRecord.usage_type, func.coalesce(func.sum(UsageRecord.quantity), 0))
        .where(
            UsageRecord.subscriber_no == subscriber_no,
            UsageRecord.year == year,
            UsageRecord.month == month,
        )
        .group_by(UsageRecord.usage_type)
    ).all()
    totals = {usage_type: int(total) for usage_type, total in rows}
    return totals.get(UsageType.PHONE, 0), totals.get(UsageType.INTERNET, 0)


def bill_summary(bill: Bill) -> dict:
    return {
        "subscriber_no": bill.subscriber_no,
        "month": bill.month,
        "year": bill.year,
        "bill_total": bill.total_amount,
        "paid_amount": bill.paid_amount,
        "remaining_balance": remaining_balance(bill),
        "status": bill.status,
        "due_date": pricing.due_date(bill.year, bill.month),
        "calculated_at": bill.calculated_at,
    }


# ---------- Add Usage ----------
def add_usage(db: Session, subscriber_no: str, year: int, month: int, usage_type: UsageType) -> dict:
    get_subscriber_or_404(db, subscriber_no)
    if usage_type == UsageType.PHONE:
        quantity, unit = pricing.PHONE_MINUTES_PER_EVENT, "MINUTES"
    else:
        quantity, unit = pricing.INTERNET_MB_PER_EVENT, "MB"
    record = UsageRecord(
        subscriber_no=subscriber_no, year=year, month=month, usage_type=usage_type, quantity=quantity
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "transaction_status": "SUCCESS",
        "usage_id": record.id,
        "subscriber_no": subscriber_no,
        "month": month,
        "year": year,
        "usage_type": usage_type,
        "quantity_added": quantity,
        "unit": unit,
    }


# ---------- Calculate Bill ----------
def calculate_bill(db: Session, subscriber_no: str, year: int, month: int) -> dict:
    get_subscriber_or_404(db, subscriber_no)
    minutes, internet_mb = usage_totals(db, subscriber_no, year, month)
    breakdown = pricing.calculate(minutes, internet_mb)

    bill = db.scalars(
        select(Bill)
        .where(Bill.subscriber_no == subscriber_no, Bill.year == year, Bill.month == month)
        .with_for_update()
    ).first()
    action = "RECALCULATED"
    if bill is None:
        action = "CREATED"
        bill = Bill(subscriber_no=subscriber_no, year=year, month=month, paid_amount=ZERO)
        db.add(bill)

    # Payments already recorded are preserved on recalculation.
    bill.phone_minutes = breakdown.phone_minutes
    bill.internet_mb = breakdown.internet_mb
    bill.phone_charge = breakdown.phone_charge
    bill.internet_charge = breakdown.internet_charge
    bill.total_amount = breakdown.total
    bill.status = bill_status(bill.total_amount, bill.paid_amount)
    bill.calculated_at = utcnow()
    db.commit()
    db.refresh(bill)
    return {"transaction_status": "SUCCESS", "action": action, "bill": bill_summary(bill)}


# ---------- Query Bill ----------
def query_bill(db: Session, subscriber_no: str, year: int, month: int) -> dict:
    get_subscriber_or_404(db, subscriber_no)
    return bill_summary(get_bill_or_404(db, subscriber_no, year, month))


# ---------- Query Bill Detailed ----------
def query_bill_detailed(
    db: Session, user: CurrentUser, subscriber_no: str, year: int, month: int, page: int, page_size: int
) -> dict:
    ensure_account_access(user, subscriber_no)
    get_subscriber_or_404(db, subscriber_no)
    bill = get_bill_or_404(db, subscriber_no, year, month)

    period_filter = (
        UsageRecord.subscriber_no == subscriber_no,
        UsageRecord.year == year,
        UsageRecord.month == month,
    )
    total_items = db.scalar(select(func.count()).select_from(UsageRecord).where(*period_filter)) or 0
    records = db.scalars(
        select(UsageRecord)
        .where(*period_filter)
        .order_by(UsageRecord.recorded_at, UsageRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    current_minutes, current_mb = usage_totals(db, subscriber_no, year, month)
    breakdown = pricing.calculate(bill.phone_minutes, bill.internet_mb)

    return {
        **bill_summary(bill),
        "phone": {
            "minutes": bill.phone_minutes,
            "included_minutes": pricing.PHONE_INCLUDED_MINUTES,
            "extra_blocks": breakdown.phone_extra_blocks,
            "block_size_minutes": pricing.PHONE_BLOCK_MINUTES,
            "block_price": pricing.PHONE_BLOCK_PRICE,
            "charge": bill.phone_charge,
        },
        "internet": {
            "usage_mb": bill.internet_mb,
            "usage_gb": pricing.mb_to_gb(bill.internet_mb),
            "included_gb": pricing.INTERNET_INCLUDED_MB // pricing.MB_PER_GB,
            "base_price": pricing.INTERNET_BASE_PRICE,
            "extra_blocks": breakdown.internet_extra_blocks,
            "block_size_gb": pricing.INTERNET_BLOCK_MB // pricing.MB_PER_GB,
            "block_price": pricing.INTERNET_BLOCK_PRICE,
            "charge": bill.internet_charge,
        },
        "recalculation_needed": (current_minutes, current_mb) != (bill.phone_minutes, bill.internet_mb),
        "usage_records": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": math.ceil(total_items / page_size) if total_items else 0,
            "items": [
                {
                    "id": r.id,
                    "usage_type": r.usage_type,
                    "quantity": r.quantity,
                    "unit": "MINUTES" if r.usage_type == UsageType.PHONE else "MB",
                    "recorded_at": r.recorded_at,
                }
                for r in records
            ],
        },
    }


# ---------- Pay Bill ----------
def pay_bill(
    db: Session,
    user: CurrentUser,
    subscriber_no: str,
    year: int,
    month: int,
    amount: Decimal,
    transaction_id: str,
) -> dict:
    ensure_account_access(user, subscriber_no)
    get_subscriber_or_404(db, subscriber_no)

    if db.scalar(select(Payment.id).where(Payment.transaction_id == transaction_id)) is not None:
        raise ApiError(
            409,
            "DUPLICATE_TRANSACTION",
            f"Transaction ID {transaction_id} has already been used. No new payment was recorded.",
        )

    bill = get_bill_or_404(db, subscriber_no, year, month, for_update=True)
    remaining = remaining_balance(bill)
    if remaining <= ZERO:
        raise ApiError(409, "BILL_ALREADY_PAID", "This bill is already fully paid.")
    if amount > remaining:
        raise ApiError(
            422,
            "AMOUNT_EXCEEDS_BALANCE",
            f"Payment amount {amount} exceeds the remaining balance {remaining}.",
            {"remainingBalance": float(remaining)},
        )

    bill.paid_amount = bill.paid_amount + amount
    bill.status = bill_status(bill.total_amount, bill.paid_amount)
    db.add(Payment(bill_id=bill.id, transaction_id=transaction_id, amount=amount, paid_by_username=user.username))
    try:
        db.commit()
    except IntegrityError:
        # Concurrent request with the same transaction ID (unique constraint).
        db.rollback()
        raise ApiError(
            409,
            "DUPLICATE_TRANSACTION",
            f"Transaction ID {transaction_id} has already been used. No new payment was recorded.",
        )
    db.refresh(bill)
    return {
        "payment_status": "SUCCESS",
        "transaction_id": transaction_id,
        "subscriber_no": subscriber_no,
        "month": month,
        "year": year,
        "paid_amount": amount,
        "total_paid": bill.paid_amount,
        "remaining_balance": remaining_balance(bill),
        "bill_status": bill.status,
    }

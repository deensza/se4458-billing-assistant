"""Database model (see docs/er-diagram.md for the ER diagram)."""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# BIGINT primary keys on PostgreSQL; INTEGER on SQLite (used only by the unit tests),
# because SQLite auto-increments only "INTEGER PRIMARY KEY" columns.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
Money = Numeric(12, 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UsageType(str, enum.Enum):
    PHONE = "PHONE"
    INTERNET = "INTERNET"


class BillStatus(str, enum.Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class UserRole(str, enum.Enum):
    SUBSCRIBER = "SUBSCRIBER"
    ADMIN = "ADMIN"


class Subscriber(Base):
    __tablename__ = "subscribers"

    subscriber_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """Login identity. A SUBSCRIBER user is linked to exactly one subscriber account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False, length=20))
    subscriber_no: Mapped[str | None] = mapped_column(
        ForeignKey("subscribers.subscriber_no"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(role = 'ADMIN') OR (subscriber_no IS NOT NULL)",
            name="ck_users_subscriber_role_has_account",
        ),
    )


class UsageRecord(Base):
    """One Add Usage event: 10 minutes of phone usage or 1 MB of internet usage."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    subscriber_no: Mapped[str] = mapped_column(ForeignKey("subscribers.subscriber_no"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    usage_type: Mapped[UsageType] = mapped_column(Enum(UsageType, native_enum=False, length=10))
    quantity: Mapped[int] = mapped_column(Integer)  # minutes (PHONE) or MB (INTERNET)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_usage_month"),
        CheckConstraint("quantity > 0", name="ck_usage_quantity_positive"),
        Index("ix_usage_subscriber_period", "subscriber_no", "year", "month"),
    )


class Bill(Base):
    """Stored result of Calculate Bill for one subscriber and billing month."""

    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscriber_no: Mapped[str] = mapped_column(ForeignKey("subscribers.subscriber_no"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    phone_minutes: Mapped[int] = mapped_column(Integer, default=0)
    internet_mb: Mapped[int] = mapped_column(Integer, default=0)
    phone_charge: Mapped[Decimal] = mapped_column(Money)
    internet_charge: Mapped[Decimal] = mapped_column(Money)
    total_amount: Mapped[Decimal] = mapped_column(Money)
    paid_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    status: Mapped[BillStatus] = mapped_column(Enum(BillStatus, native_enum=False, length=20))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="bill", order_by="Payment.id")

    __table_args__ = (
        UniqueConstraint("subscriber_no", "year", "month", name="uq_bill_subscriber_period"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_bill_month"),
        CheckConstraint("paid_amount >= 0", name="ck_bill_paid_non_negative"),
    )


class Payment(Base):
    """A simulated payment. transaction_id is globally unique (duplicate protection)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"))
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    paid_by_username: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bill: Mapped[Bill] = relationship(back_populates="payments")

    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_amount_positive"),)

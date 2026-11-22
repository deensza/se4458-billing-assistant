"""Request/response contracts (JSON uses camelCase)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator
from pydantic.alias_generators import to_camel

from .models import BillStatus, UsageType, UserRole

# Money is stored as NUMERIC(12,2) and returned as a JSON number (e.g. 80.0).
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float)]
GbOut = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float)]

SubscriberNo = Annotated[
    str, Field(pattern=r"^[0-9]{4,20}$", description="Subscriber number (digits)", examples=["5551001"])
]
Month = Annotated[int, Field(ge=1, le=12, description="Billing month (1-12)", examples=[10])]
Year = Annotated[int, Field(ge=2000, le=2100, description="Billing year", examples=[2026])]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


# ---------- Errors (documentation only) ----------
class ErrorDetail(ApiModel):
    code: str = Field(examples=["BILL_NOT_FOUND"])
    message: str
    details: object | None = None


class ErrorResponse(ApiModel):
    error: ErrorDetail


# ---------- Auth ----------
class TokenRequest(ApiModel):
    username: str = Field(min_length=1, max_length=50, examples=["user1001"])
    password: str = Field(min_length=1, max_length=128, examples=["Pass1001!"])


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Seconds until the token expires")
    role: UserRole
    subscriber_no: str | None


# ---------- Add Usage ----------
class AddUsageRequest(ApiModel):
    subscriber_no: SubscriberNo
    month: Month
    year: Year
    usage_type: UsageType = Field(
        description="Phone adds 10 minutes, Internet adds 1 MB (case-insensitive: Phone/PHONE/phone)"
    )

    @field_validator("usage_type", mode="before")
    @classmethod
    def _normalize_usage_type(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class AddUsageResponse(ApiModel):
    transaction_status: str = Field(examples=["SUCCESS"])
    usage_id: int
    subscriber_no: str
    month: int
    year: int
    usage_type: UsageType
    quantity_added: int
    unit: str = Field(examples=["MINUTES", "MB"])


# ---------- Bills ----------
class CalculateBillRequest(ApiModel):
    subscriber_no: SubscriberNo
    month: Month
    year: Year


class BillSummary(ApiModel):
    subscriber_no: str
    month: int
    year: int
    bill_total: MoneyOut
    paid_amount: MoneyOut
    remaining_balance: MoneyOut
    status: BillStatus
    due_date: date
    calculated_at: datetime


class CalculateBillResponse(ApiModel):
    transaction_status: str = Field(examples=["SUCCESS"])
    action: str = Field(description="CREATED for a new bill, RECALCULATED for an existing bill")
    bill: BillSummary


class PhoneBreakdown(ApiModel):
    minutes: int
    included_minutes: int
    extra_blocks: int
    block_size_minutes: int
    block_price: MoneyOut
    charge: MoneyOut


class InternetBreakdown(ApiModel):
    usage_mb: int
    usage_gb: GbOut
    included_gb: int
    base_price: MoneyOut
    extra_blocks: int
    block_size_gb: int
    block_price: MoneyOut
    charge: MoneyOut


class UsageRecordOut(ApiModel):
    id: int
    usage_type: UsageType
    quantity: int
    unit: str
    recorded_at: datetime


class PagedUsageRecords(ApiModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    items: list[UsageRecordOut]


class BillDetailedResponse(BillSummary):
    phone: PhoneBreakdown
    internet: InternetBreakdown
    recalculation_needed: bool = Field(
        description="True when usage was added after the bill was calculated (call Calculate Bill again)"
    )
    usage_records: PagedUsageRecords


# ---------- Payments ----------
class PayBillRequest(ApiModel):
    subscriber_no: SubscriberNo
    month: Month
    year: Year
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2, examples=[30.00])]
    transaction_id: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$", examples=["TXN-2026-10-0001"]),
    ]


class PayBillResponse(ApiModel):
    payment_status: str = Field(examples=["SUCCESS"])
    transaction_id: str
    subscriber_no: str
    month: int
    year: int
    paid_amount: MoneyOut = Field(description="Amount of this payment")
    total_paid: MoneyOut = Field(description="Total paid for this bill so far")
    remaining_balance: MoneyOut
    bill_status: BillStatus

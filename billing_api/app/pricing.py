"""Pure billing rules (Mobile_Provider_Billing_Guide.md, sections 2-4).

All arithmetic is done in integers (minutes and MB) so there is no floating-point rounding.

Phone charge    = $10 x ceil(max(0, minutes - 1000) / 1000)
Internet charge = $50 + $10 x ceil(max(0, internet_GB - 20) / 10),   1 GB = 1,000 MB
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

PHONE_MINUTES_PER_EVENT = 10
INTERNET_MB_PER_EVENT = 1

PHONE_INCLUDED_MINUTES = 1_000
PHONE_BLOCK_MINUTES = 1_000
PHONE_BLOCK_PRICE = Decimal("10.00")

MB_PER_GB = 1_000
INTERNET_BASE_PRICE = Decimal("50.00")
INTERNET_INCLUDED_MB = 20 * MB_PER_GB
INTERNET_BLOCK_MB = 10 * MB_PER_GB
INTERNET_BLOCK_PRICE = Decimal("10.00")

PAYMENT_DUE_DAYS_AFTER_MONTH_END = 15


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def phone_extra_blocks(minutes: int) -> int:
    if minutes < 0:
        raise ValueError("minutes must be >= 0")
    return _ceil_div(max(0, minutes - PHONE_INCLUDED_MINUTES), PHONE_BLOCK_MINUTES)


def internet_extra_blocks(internet_mb: int) -> int:
    if internet_mb < 0:
        raise ValueError("internet_mb must be >= 0")
    return _ceil_div(max(0, internet_mb - INTERNET_INCLUDED_MB), INTERNET_BLOCK_MB)


def phone_charge(minutes: int) -> Decimal:
    return PHONE_BLOCK_PRICE * phone_extra_blocks(minutes)


def internet_charge(internet_mb: int) -> Decimal:
    return INTERNET_BASE_PRICE + INTERNET_BLOCK_PRICE * internet_extra_blocks(internet_mb)


@dataclass(frozen=True)
class BillBreakdown:
    phone_minutes: int
    internet_mb: int
    phone_extra_blocks: int
    internet_extra_blocks: int
    phone_charge: Decimal
    internet_charge: Decimal

    @property
    def total(self) -> Decimal:
        return self.phone_charge + self.internet_charge


def calculate(phone_minutes: int, internet_mb: int) -> BillBreakdown:
    return BillBreakdown(
        phone_minutes=phone_minutes,
        internet_mb=internet_mb,
        phone_extra_blocks=phone_extra_blocks(phone_minutes),
        internet_extra_blocks=internet_extra_blocks(internet_mb),
        phone_charge=phone_charge(phone_minutes),
        internet_charge=internet_charge(internet_mb),
    )


def mb_to_gb(internet_mb: int) -> Decimal:
    return (Decimal(internet_mb) / MB_PER_GB).quantize(Decimal("0.001"))


def due_date(year: int, month: int) -> date:
    """Guide 6.1: due 15 calendar days after the end of the billing month."""
    first_of_next = date(year + (month // 12), (month % 12) + 1, 1)
    month_end = first_of_next - timedelta(days=1)
    return month_end + timedelta(days=PAYMENT_DUE_DAYS_AFTER_MONTH_END)

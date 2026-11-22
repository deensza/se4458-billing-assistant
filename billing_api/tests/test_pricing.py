"""Business rules from Mobile_Provider_Billing_Guide.md sections 2-4 and 6.1."""

from datetime import date
from decimal import Decimal

import pytest

from app import pricing


@pytest.mark.parametrize(
    "minutes, expected",
    [
        (0, "0"),
        (1_000, "0"),  # 2.1 first 1,000 minutes free
        (1_001, "10"),  # 2.2 example: 1,001 minutes costs $10
        (1_350, "10"),
        (2_000, "10"),
        (2_001, "20"),  # 2.2 example: 2,001 minutes costs $20
        (2_500, "20"),
    ],
)
def test_phone_charge_examples(minutes, expected):
    assert pricing.phone_charge(minutes) == Decimal(expected)


@pytest.mark.parametrize(
    "internet_mb, expected",
    [
        (0, "50"),  # 3.1 $50 including months with zero usage
        (20_000, "50"),  # 20 GB costs $50
        (20_001, "60"),  # partially used block charged as a full block
        (21_000, "60"),  # 21 GB costs $60
        (30_000, "60"),  # 30 GB costs $60
        (30_001, "70"),
        (35_000, "70"),  # 35 GB costs $70
    ],
)
def test_internet_charge_examples(internet_mb, expected):
    assert pricing.internet_charge(internet_mb) == Decimal(expected)


def test_worked_example_total_is_80():
    """Guide 4.3: 1,350 minutes and 35 GB -> $10 + $70 = $80."""
    b = pricing.calculate(1_350, 35_000)
    assert (b.phone_charge, b.internet_charge, b.total) == (Decimal("10"), Decimal("70"), Decimal("80"))
    assert (b.phone_extra_blocks, b.internet_extra_blocks) == (1, 2)


@pytest.mark.parametrize("fn", [pricing.phone_charge, pricing.internet_charge])
def test_negative_usage_is_rejected(fn):
    with pytest.raises(ValueError):
        fn(-1)


@pytest.mark.parametrize(
    "year, month, expected",
    [(2026, 10, date(2026, 11, 15)), (2026, 12, date(2027, 1, 15)), (2028, 2, date(2028, 3, 15))],
)
def test_due_date_is_15_days_after_month_end(year, month, expected):
    assert pricing.due_date(year, month) == expected


def test_mb_to_gb_uses_1000_mb_per_gb():
    assert pricing.mb_to_gb(35_000) == Decimal("35.000")
    assert pricing.mb_to_gb(20_001) == Decimal("20.001")

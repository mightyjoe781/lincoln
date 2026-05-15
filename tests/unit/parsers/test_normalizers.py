from datetime import date
from decimal import Decimal

import pytest

from app.parsers.normalizers import normalize_currency, parse_amount, parse_date


@pytest.mark.parametrize("raw,expected", [
    ("15/05/2024", date(2024, 5, 15)),
    ("May 15 2024", date(2024, 5, 15)),
    ("2024-05-15", date(2024, 5, 15)),
    ("05-15-2024", date(2024, 5, 15)),
    ("", None),
    (None, None),
    ("not-a-date", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$1,234.56", Decimal("1234.56")),
    ("USD 1234.56", Decimal("1234.56")),
    ("1.234,56 EUR", Decimal("1234.56")),
    ("1234.56", Decimal("1234.56")),
    ("", None),
    (None, None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$", "USD"),
    ("€", "EUR"),
    ("USD", "USD"),
    ("usd", "USD"),
    ("", None),
    (None, None),
])
def test_normalize_currency(raw, expected):
    assert normalize_currency(raw) == expected

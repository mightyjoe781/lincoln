from datetime import date
from decimal import Decimal

import pytest

from app.parsers.normalizers import normalize_currency, parse_amount, parse_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("15/05/2024", date(2024, 5, 15)),
        ("May 15 2024", date(2024, 5, 15)),
        ("2024-05-15", date(2024, 5, 15)),
        ("05-15-2024", date(2024, 5, 15)),
        ("", None),
        (None, None),
        ("not-a-date", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.56", Decimal("1234.56")),
        ("USD 1234.56", Decimal("1234.56")),
        ("1.234,56 EUR", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$", "USD"),
        ("€", "EUR"),
        ("USD", "USD"),
        ("usd", "USD"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_currency(raw, expected):
    assert normalize_currency(raw) == expected


# ── parse_date edge cases ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("   ", None),  # whitespace-only
        ("\t\n", None),  # tabs and newlines
        ("00/00/0000", None),  # structurally valid but nonsensical
        ("2024-02-30", None),  # impossible calendar date
        ("15 May 2024", date(2024, 5, 15)),  # natural language with space
        ("2024/05/15", date(2024, 5, 15)),  # forward-slash ISO variant
        ("١٥/٠٥/٢٠٢٤", None),  # Arabic-Indic digits — returns None gracefully
    ],
)
def test_parse_date_edge_cases(raw, expected):
    assert parse_date(raw) == expected


# ── parse_amount edge cases ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("   ", None),  # whitespace-only
        ("(1,234.56)", None),  # parenthetical negative — not yet supported; assert None not crash
        ("-1234.56", Decimal("-1234.56")),  # explicit negative
        ("0.00", Decimal("0.00")),  # zero
        (
            "1.234",
            Decimal("1.234"),
        ),  # ambiguous European vs decimal — falls through to Decimal directly
        (
            "CHF 9'999.00",
            None,
        ),  # Swiss apostrophe thousands separator — currently unsupported; no crash
    ],
)
def test_parse_amount_edge_cases(raw, expected):
    assert parse_amount(raw) == expected


# ── normalize_currency edge cases ─────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("   ", None),  # whitespace-only
        ("A$", "AUD"),  # multi-char symbol
        ("C$", "CAD"),  # multi-char symbol
        ("£", "GBP"),
        ("¥", "JPY"),
        ("₹", "INR"),
        ("XYZ", None),  # unknown ISO code
        ("DOLLAR", None),  # word-form — not recognised
        ("sgd", "SGD"),  # lowercase known ISO
        ("hkd", "HKD"),
    ],
)
def test_normalize_currency_edge_cases(raw, expected):
    assert normalize_currency(raw) == expected

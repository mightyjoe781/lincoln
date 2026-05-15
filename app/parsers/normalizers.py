import re
from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil import parser as dateutil_parser

SYMBOL_TO_ISO = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₩": "KRW",
    "₣": "CHF",
    "A$": "AUD",
    "C$": "CAD",
}
KNOWN_ISO = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "INR",
    "CHF",
    "AUD",
    "CAD",
    "KRW",
    "SGD",
    "HKD",
    "NZD",
    "MXN",
    "BRL",
}


_YEAR_FIRST_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def parse_date(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    s = raw.strip()
    try:
        # ISO / year-first formats (e.g. "2024-07-01") must not use dayfirst
        # because dateutil with dayfirst=True reorders the month/day tokens.
        if _YEAR_FIRST_RE.match(s):
            return dateutil_parser.parse(s, yearfirst=True, dayfirst=False).date()
        return dateutil_parser.parse(s, dayfirst=True).date()
    except (ValueError, OverflowError):
        return None


def parse_amount(raw: str | None) -> Decimal | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip()
    # Remove currency symbols and known ISO codes
    for sym in sorted(SYMBOL_TO_ISO, key=len, reverse=True):
        cleaned = cleaned.replace(sym, "")
    for iso in KNOWN_ISO:
        cleaned = re.sub(rf"\b{iso}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    # European-style with thousand-dot: 1.234,56 → 1234.56
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    # European-style decimal-comma without thousands: 850,00 → 850.00
    elif re.match(r"^\d+,\d{1,2}$", cleaned):
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def normalize_currency(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for sym, iso in sorted(SYMBOL_TO_ISO.items(), key=lambda x: len(x[0]), reverse=True):
        if raw == sym:
            return iso
    upper = raw.upper()
    if upper in KNOWN_ISO:
        return upper
    return None

from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.base import ParseError
from app.parsers.csv_statement import CsvStatementParser

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


def test_parse_standard_csv():
    data = (FIXTURES / "sample_statement.csv").read_bytes()
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 10
    assert rows[0].amount == Decimal("5000.00")
    assert rows[0].currency == "USD"


def test_parse_messy_csv_dates():
    data = (FIXTURES / "sample_statement_messy.csv").read_bytes()
    rows = CsvStatementParser().parse(data)
    bad_row = next(r for r in rows if r.transaction_date is None)
    assert bad_row.parse_warnings


def test_parse_empty_csv_returns_empty_list():
    rows = CsvStatementParser().parse(b"date,description,amount\n")
    assert rows == []


def test_parse_missing_required_column_raises():
    with pytest.raises(ParseError):
        CsvStatementParser().parse(b"foo,bar\n1,2\n")


def test_parse_header_only_returns_empty_list():
    """A file with headers but zero data rows should return []."""
    data = b"date,description,amount\n"
    rows = CsvStatementParser().parse(data)
    assert rows == []


def test_parse_all_null_row_is_skipped():
    """A row where every cell is empty should be silently dropped."""
    data = b"date,description,amount\n,,,\n2024-01-01,Salary,1000\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].description == "Salary"


def test_parse_large_csv_returns_correct_count():
    """Parser should handle >1 000 rows without error or truncation."""
    header = "date,description,amount\n"
    row = "2024-01-01,Test,100.00\n"
    data = (header + row * 1100).encode()
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1100


def test_parse_bom_prefix_is_handled():
    """UTF-8 BOM (\\xef\\xbb\\xbf) should be stripped and not break column mapping."""
    data = b"\xef\xbb\xbfdate,description,amount\n2024-01-01,BOM Test,50.00\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("50.00")


def test_parse_debit_credit_variants():
    """All debit/credit shorthand values should normalise correctly."""
    rows_data = [
        ("DR", "debit"),
        ("dr", "debit"),
        ("D", "debit"),
        ("CR", "credit"),
        ("cr", "credit"),
        ("C", "credit"),
        ("DEBIT", "debit"),
        ("CREDIT", "credit"),
    ]
    for raw, expected in rows_data:
        csv_bytes = (f"date,description,amount,debit_credit\n2024-01-01,Test,100,{raw}\n").encode()
        rows = CsvStatementParser().parse(csv_bytes)
        assert rows[0].debit_credit == expected, f"Failed for raw={raw!r}"


def test_parse_column_aliases_recognised():
    """Alternative column names (narration, trans_date, txn_id) map correctly."""
    data = b"trans_date,narration,transaction_amount,ccy,txn_id\n2024-03-01,Rent,-1500,USD,REF001\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].description == "Rent"
    assert rows[0].currency == "USD"
    assert rows[0].reference == "REF001"


def test_parse_empty_bytes_returns_empty_list():
    """Completely empty bytes (no headers at all) should return []."""
    rows = CsvStatementParser().parse(b"")
    assert rows == []


def test_parse_amount_warning_added_for_unparseable():
    """An unparseable amount should NOT raise but should add a warning to the row."""
    data = b"date,description,amount\n2024-01-01,Test,NOT_A_NUMBER\n"
    rows = CsvStatementParser().parse(data)
    assert len(rows) == 1
    assert rows[0].amount is None
    assert any("unparseable amount" in w for w in rows[0].parse_warnings)

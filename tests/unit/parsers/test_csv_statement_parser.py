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

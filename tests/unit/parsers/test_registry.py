import pytest

from app.parsers.base import ParseError
from app.parsers.csv_statement import CsvStatementParser
from app.parsers.pdf_invoice import PdfInvoiceParser
from app.parsers.registry import get_file_type, get_parser


def test_get_parser_pdf():
    assert isinstance(get_parser("application/pdf"), PdfInvoiceParser)


def test_get_parser_csv_text():
    assert isinstance(get_parser("text/csv"), CsvStatementParser)


def test_get_parser_text_plain():
    assert isinstance(get_parser("text/plain"), CsvStatementParser)


def test_get_parser_unknown_raises():
    with pytest.raises(ParseError, match="No parser for mime type"):
        get_parser("image/jpeg")


def test_get_parser_octet_stream_raises():
    """application/octet-stream is not in the registry — raises ParseError."""
    with pytest.raises(ParseError, match="No parser for mime type"):
        get_parser("application/octet-stream")


def test_get_file_type_pdf():
    assert get_file_type("application/pdf") == "pdf_invoice"


def test_get_file_type_csv():
    assert get_file_type("text/csv") == "csv_statement"


def test_get_file_type_text_plain():
    assert get_file_type("text/plain") == "csv_statement"


def test_get_file_type_unknown_returns_unknown():
    assert get_file_type("video/mp4") == "unknown"


def test_get_file_type_octet_stream_returns_unknown():
    assert get_file_type("application/octet-stream") == "unknown"

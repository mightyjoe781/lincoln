import pytest

from app.parsers.base import ParseError
from app.parsers.pdf_invoice import PdfInvoiceParser


def test_parse_corrupted_pdf_raises_parse_error():
    with pytest.raises(ParseError):
        PdfInvoiceParser().parse(b"not a pdf at all")


def test_parse_empty_bytes_raises_parse_error():
    with pytest.raises(ParseError):
        PdfInvoiceParser().parse(b"")

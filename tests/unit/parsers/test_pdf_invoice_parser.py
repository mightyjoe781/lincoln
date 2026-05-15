from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.parsers.base import ParseError
from app.parsers.pdf_invoice import PdfInvoiceParser


def test_parse_corrupted_pdf_raises_parse_error():
    with pytest.raises(ParseError):
        PdfInvoiceParser().parse(b"not a pdf at all")


def test_parse_empty_bytes_raises_parse_error():
    with pytest.raises(ParseError):
        PdfInvoiceParser().parse(b"")


def test_parse_password_protected_pdf_raises_parse_error():
    """pdfplumber raises when it encounters an encrypted PDF it cannot open."""
    with patch("pdfplumber.open", side_effect=Exception("file has not been decrypted")):
        with pytest.raises(ParseError, match="Cannot open PDF"):
            PdfInvoiceParser().parse(b"%PDF-1.4 fake encrypted content")


def test_parse_image_only_pdf_returns_result_with_empty_text():
    """An image-only scan has no extractable text; parser should return a result
    with raw_text='' and all fields None rather than crashing."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = None  # image-only page
    mock_page.extract_tables.return_value = []
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = PdfInvoiceParser().parse(b"%PDF-fake")

    assert result.raw_text == ""
    assert result.vendor_name is None
    assert result.total_amount is None
    assert "vendor_name not found" in result.parse_warnings


def test_parse_pdf_with_vendor_and_total():
    """Verify field extraction from a PDF whose text contains known patterns."""
    fake_text = (
        "ACME Corp Inc\n"
        "Invoice Date: 2024-05-15\n"
        "Due Date: 2024-06-15\n"
        "Invoice #: INV-0042\n"
        "Total: $1,500.00\n"
        "Tax: $150.00\n"
    )
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_page.extract_tables.return_value = []
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = PdfInvoiceParser().parse(b"%PDF-fake")

    assert result.invoice_number == "INV-0042"
    assert result.invoice_date == date(2024, 5, 15)
    assert result.due_date == date(2024, 6, 15)
    assert result.total_amount == Decimal("1500.00")
    assert result.tax_amount == Decimal("150.00")


def test_parse_pdf_line_item_extraction():
    """Lines matching <description><2+ spaces><amount> should be captured as line items."""
    fake_text = "Consulting Services  800.00\nSoftware Licence  700.00\nTotal: $1,500.00\n"
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fake_text
    mock_page.extract_tables.return_value = []
    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)

    with patch("pdfplumber.open", return_value=mock_pdf):
        result = PdfInvoiceParser().parse(b"%PDF-fake")

    assert len(result.line_items) == 2
    descriptions = [li.description for li in result.line_items]
    assert "Consulting Services" in descriptions
    assert "Software Licence" in descriptions

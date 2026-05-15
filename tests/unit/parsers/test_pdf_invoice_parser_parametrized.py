from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.pdf_invoice import PdfInvoiceParser

SAMPLES = Path(__file__).parent.parent.parent.parent / "test-samples"

CASES = [
    pytest.param(
        "invoice_complete.pdf",
        {
            "vendor_name": "Acme Corp",
            "invoice_number": "INV-2024-0042",
            "invoice_date": date(2024, 3, 15),
            "due_date": date(2024, 4, 15),
            "total_amount": Decimal("12694.50"),
            "tax_amount": Decimal("994.50"),
            "currency": "USD",
            "line_item_count": 4,
        },
        set(),
        id="complete",
    ),
    pytest.param(
        "invoice_partial.pdf",
        {
            "vendor_name": None,
            "invoice_number": "INV-2024-0099",
            "invoice_date": date(2024, 5, 10),
            "due_date": None,
            "total_amount": Decimal("2350.00"),
            "line_item_count": 2,
        },
        {"vendor_name not found", "due date not found"},
        id="partial",
    ),
    pytest.param(
        "invoice_minimal.pdf",
        {
            "vendor_name": None,
            "invoice_number": None,
            "invoice_date": date(2024, 6, 15),
            "due_date": None,
            "total_amount": Decimal("875.00"),
        },
        {"vendor_name not found", "invoice_number not found", "due date not found"},
        id="minimal",
    ),
    pytest.param(
        "invoice_multipage.pdf",
        {
            "vendor_name": "GlobalTech Solutions Ltd",
            "invoice_number": "GT-2024-0188",
            "invoice_date": date(2024, 7, 1),
            "due_date": date(2024, 7, 31),
            "total_amount": Decimal("45342.00"),
            "tax_amount": Decimal("4122.00"),
            "currency": "USD",
            "line_item_count": 11,
        },
        set(),
        id="multipage",
    ),
    pytest.param(
        "invoice_non_standard.pdf",
        {
            "vendor_name": "Sunrise Digital Agency",
            "invoice_number": "SDA-9901",
            "invoice_date": date(2024, 8, 5),
            "due_date": date(2024, 9, 4),
            "total_amount": Decimal("5092.50"),
            "tax_amount": Decimal("242.50"),
            "currency": "USD",
            "line_item_count": 3,
        },
        set(),
        id="non_standard",
    ),
    pytest.param(
        "invoice_euro_format.pdf",
        {
            "vendor_name": "Muster GmbH",
            "invoice_number": "RG-2024-0077",
            "invoice_date": date(2024, 9, 15),
            "due_date": date(2024, 10, 15),
            "total_amount": Decimal("152617.50"),
            "tax_amount": Decimal("24367.50"),
            "currency": "EUR",
            "line_item_count": 3,
        },
        set(),
        id="euro_format",
    ),
]


@pytest.mark.parametrize("pdf_name,expected_fields,expected_warnings", CASES)
def test_parse_invoice(pdf_name, expected_fields, expected_warnings):
    path = SAMPLES / pdf_name
    if not path.exists():
        pytest.skip(f"fixture not found: {pdf_name}")
    result = PdfInvoiceParser().parse(path.read_bytes())

    for field, expected in expected_fields.items():
        if field == "line_item_count":
            assert len(result.line_items) == expected, (
                f"{pdf_name}: expected {expected} line items, got {len(result.line_items)}"
            )
        else:
            actual = getattr(result, field)
            assert actual == expected, (
                f"{pdf_name}: {field} expected {expected!r}, got {actual!r}"
            )

    actual_warnings = set(result.parse_warnings)
    assert actual_warnings == expected_warnings, (
        f"{pdf_name}: warnings mismatch\n  expected: {expected_warnings}\n  actual:   {actual_warnings}"
    )

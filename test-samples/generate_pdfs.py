"""
Generate test PDF invoices for the Lincoln parser.

Run from the project root:
    pip install fpdf2
    python test-samples/generate_pdfs.py

Produces:
    test-samples/invoice_complete.pdf          -- all fields present, parser should extract everything
    test-samples/invoice_partial.pdf           -- missing vendor + due date, parser warns
    test-samples/invoice_minimal.pdf           -- only total and date, most fields missing
    test-samples/invoice_multipage.pdf         -- 2 pages, many line items
    test-samples/invoice_non_standard.pdf      -- uses "Amount Due" / "Bill From" / "Inv No" labels
    test-samples/invoice_euro_format.pdf       -- EUR currency, European number format
"""

from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).parent


# ── helpers ──────────────────────────────────────────────────────────────────


def header(pdf: FPDF, title: str = "INVOICE") -> None:
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.ln(4)


def divider(pdf: FPDF) -> None:
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)


def kv(pdf: FPDF, key: str, value: str, bold_key: bool = True) -> None:
    pdf.set_font("Helvetica", "B" if bold_key else "", 10)
    pdf.cell(50, 6, key, ln=False)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, value, ln=True)


def line_items_table(pdf: FPDF, items: list[tuple]) -> None:
    """items: list of (description, qty, unit_price, total)"""
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(90, 7, "Description", border=1, fill=True)
    pdf.cell(20, 7, "Qty", border=1, fill=True, align="C")
    pdf.cell(35, 7, "Unit Price", border=1, fill=True, align="R")
    pdf.cell(35, 7, "Total", border=1, fill=True, align="R", ln=True)
    pdf.set_font("Helvetica", "", 10)
    for desc, qty, unit, total in items:
        pdf.cell(90, 6, desc, border=1)
        pdf.cell(20, 6, str(qty), border=1, align="C")
        pdf.cell(35, 6, f"${unit:,.2f}", border=1, align="R")
        pdf.cell(35, 6, f"${total:,.2f}", border=1, align="R", ln=True)
    pdf.ln(2)


# ── 1. Complete invoice ───────────────────────────────────────────────────────


def invoice_complete() -> None:
    pdf = FPDF()
    pdf.add_page()
    header(pdf)

    kv(pdf, "Vendor:", "Acme Corp")
    kv(pdf, "Bill From:", "Acme Corp, 123 Main St, San Francisco, CA 94105")
    pdf.ln(2)
    kv(pdf, "Invoice #:", "INV-2024-0042")
    kv(pdf, "Invoice Date:", "2024-03-15")
    kv(pdf, "Due Date:", "2024-04-15")
    pdf.ln(4)
    divider(pdf)

    items = [
        ("Web Development Services", 40, 150.00, 6000.00),
        ("UI/UX Design", 20, 120.00, 2400.00),
        ("DevOps Setup", 10, 180.00, 1800.00),
        ("Project Management", 15, 100.00, 1500.00),
    ]
    line_items_table(pdf, items)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(145, 6, "Subtotal", align="R")
    pdf.cell(35, 6, "$11,700.00", align="R", ln=True)
    kv(pdf, "", "")
    pdf.cell(145, 6, "Tax (8.5%):", align="R")
    pdf.cell(35, 6, "$994.50", align="R", ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(145, 8, "Total:", align="R")
    pdf.cell(35, 8, "$12,694.50", align="R", ln=True)

    pdf.output(str(OUT / "invoice_complete.pdf"))
    print("  created: invoice_complete.pdf")


# ── 2. Partial invoice (missing vendor + due date) ────────────────────────────


def invoice_partial() -> None:
    pdf = FPDF()
    pdf.add_page()
    header(pdf)

    # No vendor / bill-from line
    kv(pdf, "Invoice No:", "INV-2024-0099")
    kv(pdf, "Invoice Date:", "May 10 2024")
    # Due date intentionally omitted
    pdf.ln(4)
    divider(pdf)

    items = [
        ("Consulting Services", 8, 200.00, 1600.00),
        ("Report Writing", 5, 150.00, 750.00),
    ]
    line_items_table(pdf, items)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(145, 8, "Total:", align="R")
    pdf.cell(35, 8, "$2,350.00", align="R", ln=True)

    pdf.output(str(OUT / "invoice_partial.pdf"))
    print("  created: invoice_partial.pdf")


# ── 3. Minimal invoice (only date + total) ────────────────────────────────────


def invoice_minimal() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(
        0,
        8,
        "Payment Request\n\n"
        "Date: 15/06/2024\n\n"
        "Please remit payment for services rendered.\n\n"
        "Amount Due: $875.00\n",
    )
    pdf.output(str(OUT / "invoice_minimal.pdf"))
    print("  created: invoice_minimal.pdf")


# ── 4. Multi-page invoice ─────────────────────────────────────────────────────


def invoice_multipage() -> None:
    pdf = FPDF()
    pdf.add_page()
    header(pdf, "INVOICE — Page 1 of 2")

    kv(pdf, "Vendor:", "GlobalTech Solutions Ltd")
    kv(pdf, "Invoice #:", "GT-2024-0188")
    kv(pdf, "Invoice Date:", "2024-07-01")
    kv(pdf, "Due Date:", "2024-07-31")
    pdf.ln(4)
    divider(pdf)

    items_p1 = [
        ("Backend API Development", 60, 175.00, 10500.00),
        ("Database Architecture", 25, 200.00, 5000.00),
        ("Security Audit", 15, 250.00, 3750.00),
        ("Load Testing & Optimization", 20, 160.00, 3200.00),
        ("Code Review Sessions", 12, 140.00, 1680.00),
        ("CI/CD Pipeline Setup", 18, 155.00, 2790.00),
        ("Documentation", 30, 90.00, 2700.00),
        ("Training Sessions", 10, 200.00, 2000.00),
    ]
    line_items_table(pdf, items_p1)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 6, "Continued on next page...", ln=True, align="R")

    pdf.add_page()
    header(pdf, "INVOICE — Page 2 of 2")
    kv(pdf, "Vendor:", "GlobalTech Solutions Ltd")
    kv(pdf, "Invoice #:", "GT-2024-0188 (continued)")
    pdf.ln(4)
    divider(pdf)

    items_p2 = [
        ("Cloud Infrastructure Setup", 22, 185.00, 4070.00),
        ("Monitoring & Alerting", 14, 145.00, 2030.00),
        ("Post-launch Support (30 days)", 1, 3500.00, 3500.00),
    ]
    line_items_table(pdf, items_p2)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(145, 6, "Subtotal:", align="R")
    pdf.cell(35, 6, "$41,220.00", align="R", ln=True)
    pdf.cell(145, 6, "Tax (10%):", align="R")
    pdf.cell(35, 6, "$4,122.00", align="R", ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(145, 8, "Grand Total:", align="R")
    pdf.cell(35, 8, "$45,342.00", align="R", ln=True)

    pdf.output(str(OUT / "invoice_multipage.pdf"))
    print("  created: invoice_multipage.pdf")


# ── 5. Non-standard labels ────────────────────────────────────────────────────


def invoice_non_standard() -> None:
    """Uses 'Amount Due', 'Bill From', 'Inv No' instead of standard labels."""
    pdf = FPDF()
    pdf.add_page()
    header(pdf, "TAX INVOICE")

    kv(pdf, "Bill From:", "Sunrise Digital Agency")
    kv(pdf, "Inv No:", "SDA-9901")
    kv(pdf, "Invoice Date:", "August 5 2024")
    kv(pdf, "Payment Due:", "September 4 2024")
    pdf.ln(4)
    divider(pdf)

    items = [
        ("Social Media Campaign", 1, 3200.00, 3200.00),
        ("Content Creation (10 posts)", 10, 120.00, 1200.00),
        ("Analytics Report", 1, 450.00, 450.00),
    ]
    line_items_table(pdf, items)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(145, 6, "VAT (5%):", align="R")
    pdf.cell(35, 6, "$242.50", align="R", ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(145, 8, "Amount Due:", align="R")
    pdf.cell(35, 8, "$5,092.50", align="R", ln=True)

    pdf.output(str(OUT / "invoice_non_standard.pdf"))
    print("  created: invoice_non_standard.pdf")


# ── 6. Euro / European format ─────────────────────────────────────────────────


def invoice_euro_format() -> None:
    pdf = FPDF()
    pdf.add_page()
    header(pdf, "RECHNUNG / INVOICE")

    kv(pdf, "Vendor:", "Muster GmbH")
    kv(pdf, "Invoice #:", "RG-2024-0077")
    kv(pdf, "Invoice Date:", "15.09.2024")
    kv(pdf, "Due Date:", "15.10.2024")
    pdf.ln(4)
    divider(pdf)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(90, 7, "Leistung / Service", border=1, fill=True)
    pdf.cell(20, 7, "Menge", border=1, fill=True, align="C")
    pdf.cell(35, 7, "Einzelpreis", border=1, fill=True, align="R")
    pdf.cell(35, 7, "Betrag", border=1, fill=True, align="R", ln=True)
    pdf.set_font("Helvetica", "", 10)
    rows = [
        ("Softwareentwicklung", "80", "1.250,00", "100.000,00"),
        ("Beratung / Consulting", "20", "850,00", "17.000,00"),
        ("Projektmanagement", "15", "750,00", "11.250,00"),
    ]
    for desc, qty, unit, total in rows:
        pdf.cell(90, 6, desc, border=1)
        pdf.cell(20, 6, qty, border=1, align="C")
        pdf.cell(35, 6, f"EUR {unit}", border=1, align="R")
        pdf.cell(35, 6, f"EUR {total}", border=1, align="R", ln=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(145, 6, "Nettobetrag (Subtotal):", align="R")
    pdf.cell(35, 6, "EUR 128.250,00", align="R", ln=True)
    pdf.cell(145, 6, "MwSt. / VAT (19%):", align="R")
    pdf.cell(35, 6, "EUR 24.367,50", align="R", ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(145, 8, "Gesamtbetrag / Total:", align="R")
    pdf.cell(35, 8, "EUR 152.617,50", align="R", ln=True)

    pdf.output(str(OUT / "invoice_euro_format.pdf"))
    print("  created: invoice_euro_format.pdf")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Generating test PDFs...")
    invoice_complete()
    invoice_partial()
    invoice_minimal()
    invoice_multipage()
    invoice_non_standard()
    invoice_euro_format()
    print("\nDone. Upload via: http://localhost:8000/docs -> POST /api/v1/documents/upload")
    print("\nExpected parser behaviour:")
    print("  invoice_complete.pdf      -> all fields extracted, 4 line items")
    print("  invoice_partial.pdf       -> vendor=None (warning), due_date=None (warning)")
    print("  invoice_minimal.pdf       -> only invoice_date + total_amount extracted")
    print(
        "  invoice_multipage.pdf     -> vendor + all fields from page 1, line items from both pages"
    )
    print("  invoice_non_standard.pdf  -> tests 'Bill From', 'Inv No', 'Amount Due', 'VAT' labels")
    print("  invoice_euro_format.pdf   -> EUR currency, European number format 1.234,56")

import io
import re

import pdfplumber

from app.parsers.base import InvoiceParseResult, ParseError, ParsedLineItem
from app.parsers.normalizers import normalize_currency, parse_amount, parse_date


class PdfInvoiceParser:
    def parse(self, data: bytes) -> InvoiceParseResult:
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages_text = [page.extract_text() or "" for page in pdf.pages]
        except Exception as exc:
            raise ParseError(f"Cannot open PDF: {exc}") from exc

        full_text = "\n".join(pages_text)
        result = InvoiceParseResult(raw_text=full_text)
        warnings = result.parse_warnings

        result.vendor_name = self._extract_vendor(full_text, warnings)
        result.invoice_date = self._extract_date(full_text, r"(?:invoice\s+date|date)[:\s]+([^\n]+)", warnings, "invoice date")
        result.due_date = self._extract_date(full_text, r"(?:due\s+date|payment\s+due)[:\s]+([^\n]+)", warnings, "due date")
        result.invoice_number = self._extract_invoice_number(full_text, warnings)
        result.currency, result.total_amount = self._extract_total(full_text, warnings)
        result.tax_amount = self._extract_tax(full_text, warnings)
        result.line_items = self._extract_line_items(pdf_pages_text=pages_text, warnings=warnings)

        return result

    def _extract_vendor(self, text: str, warnings: list[str]) -> str | None:
        for pattern in [
            r"(?:from|vendor|bill\s+from|sold\s+by)[:\s]+([^\n]+)",
            r"^([A-Z][A-Za-z\s&.,]+(?:Inc|LLC|Ltd|Corp|Co)\.?)",
        ]:
            m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if m:
                return m.group(1).strip()
        warnings.append("vendor_name not found")
        return None

    def _extract_date(self, text: str, pattern: str, warnings: list[str], field: str):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return parse_date(m.group(1).strip())
        warnings.append(f"{field} not found")
        return None

    def _extract_invoice_number(self, text: str, warnings: list[str]) -> str | None:
        m = re.search(r"(?:invoice\s*#?|inv\s*#?|invoice\s+no\.?)[:\s]*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        warnings.append("invoice_number not found")
        return None

    def _extract_total(self, text: str, warnings: list[str]) -> tuple[str | None, object]:
        m = re.search(r"(?:total|amount\s+due|grand\s+total)[:\s]*([A-Z$€£¥₹]{0,5}\s*[\d,. ]+)", text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            currency_match = re.search(r"([A-Z$€£¥₹]{1,5})", raw)
            currency = normalize_currency(currency_match.group(1)) if currency_match else None
            amount = parse_amount(raw)
            return currency, amount
        warnings.append("total_amount not found")
        return None, None

    def _extract_tax(self, text: str, warnings: list[str]):
        m = re.search(r"(?:tax|vat|gst)[:\s]*([A-Z$€£¥₹]{0,5}\s*[\d,.]+)", text, re.IGNORECASE)
        if m:
            return parse_amount(m.group(1).strip())
        return None

    def _extract_line_items(self, pdf_pages_text: list[str], warnings: list[str]) -> list[ParsedLineItem]:
        items = []
        for page_text in pdf_pages_text:
            # Look for simple table rows: description + amount
            for line in page_text.splitlines():
                m = re.match(r"^(.+?)\s{2,}(\d[\d,. ]+)$", line.strip())
                if m:
                    desc = m.group(1).strip()
                    total = parse_amount(m.group(2))
                    if total and len(desc) > 2:
                        items.append(ParsedLineItem(description=desc, total=total))
        return items

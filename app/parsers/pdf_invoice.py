import io
import re

import pdfplumber

from app.parsers.base import InvoiceParseResult, ParsedLineItem, ParseError
from app.parsers.normalizers import normalize_currency, parse_amount, parse_date

_DESC_ALIASES = {"description", "item", "service", "leistung", "leistung / service"}
_QTY_ALIASES = {"qty", "quantity", "menge", "units"}
_UPRICE_ALIASES = {"unit price", "unit", "rate", "einzelpreis", "preis"}
_TOTAL_ALIASES = {"total", "amount", "betrag", "line total"}

_SKIP_ROW_RE = re.compile(
    r"^\s*(sub.?total|grand\s+total|gesamtbetrag|nettobetrag)\s*$", re.IGNORECASE
)


class PdfInvoiceParser:
    def parse(self, data: bytes) -> InvoiceParseResult:
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages_text = [page.extract_text() or "" for page in pdf.pages]
                full_text = "\n".join(pages_text)
                result = InvoiceParseResult(raw_text=full_text)
                warnings = result.parse_warnings

                result.vendor_name = self._extract_vendor(full_text, warnings)
                result.invoice_date = self._extract_date(
                    full_text, r"(?:invoice\s+date|date)[:\s]+([^\n]+)", warnings, "invoice date"
                )
                result.due_date = self._extract_date(
                    full_text,
                    r"(?:due\s+date|payment\s+due)[:\s]+([^\n]+)",
                    warnings,
                    "due date",
                )
                result.invoice_number = self._extract_invoice_number(full_text, warnings)
                result.currency, result.total_amount = self._extract_total(full_text, warnings)
                result.tax_amount = self._extract_tax(full_text, warnings)
                result.line_items = self._extract_line_items(pdf.pages, pages_text, warnings)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(f"Cannot open PDF: {exc}") from exc

        return result

    def _extract_vendor(self, text: str, warnings: list[str]) -> str | None:
        for pattern in [
            r"(?:from|vendor|bill\s+from|sold\s+by)[:\s]+([^\n]+)",
            r"^([A-Z][A-Za-z&., ]+?(?:Inc|LLC|Ltd|Corp|GmbH|Co)\.?)$",
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
        # Require "#", "no", or "number" after invoice/inv to avoid matching the document title
        m = re.search(
            r"(?:invoice\s*#|invoice\s+no\.?|invoice\s+number|inv\s+no\.?|inv\s*#)[:\s]*([A-Z0-9][A-Z0-9\-/]+)",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        warnings.append("invoice_number not found")
        return None

    def _extract_total(self, text: str, warnings: list[str]) -> tuple[str | None, object]:
        # \b prevents matching "total" inside "Subtotal"; \d required to avoid letter-only captures
        m = re.search(
            r"\b(?:total|amount\s+due|grand\s+total|gesamtbetrag)[:\s]*([A-Z$€£¥₹]{0,5}\s*\d[\d,. ]*)",
            text,
            re.IGNORECASE,
        )
        if m:
            raw = m.group(1).strip()
            currency_match = re.search(r"([A-Z$€£¥₹]{1,5})", raw)
            currency = normalize_currency(currency_match.group(1)) if currency_match else None
            amount = parse_amount(raw)
            if amount is not None:
                return currency, amount
        warnings.append("total_amount not found")
        return None, None

    def _extract_tax(self, text: str, warnings: list[str]):
        # Allow optional rate annotation like "(8.5%)" or "/ VAT (19%)" between label and amount
        m = re.search(
            r"\b(?:tax|vat|gst|hst|mwst\.?|ust)[^:\n]*?[:\s]+([A-Z$€£¥₹]{0,5}\s*\d[\d,. ]*)",
            text,
            re.IGNORECASE,
        )
        if m:
            return parse_amount(m.group(1).strip())
        return None

    def _extract_line_items(
        self, pdf_pages, pages_text: list[str], warnings: list[str]
    ) -> list[ParsedLineItem]:
        items = []
        for page, page_text in zip(pdf_pages, pages_text):
            table_items = self._extract_line_items_from_table(page, warnings)
            if table_items:
                items.extend(table_items)
            else:
                items.extend(self._extract_line_items_regex(page_text, warnings))
        return items

    def _extract_line_items_from_table(
        self, page, warnings: list[str]
    ) -> list[ParsedLineItem]:
        tables = page.extract_tables(
            {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
        )
        if not tables:
            return []

        items = []
        for table in tables:
            if not table or len(table) < 2:
                continue

            # Identify column indices from the header row
            header_row = [str(cell or "").lower().strip() for cell in table[0]]
            desc_col = qty_col = uprice_col = total_col = None
            for i, cell in enumerate(header_row):
                if cell in _DESC_ALIASES:
                    desc_col = i
                elif cell in _QTY_ALIASES:
                    qty_col = i
                elif cell in _UPRICE_ALIASES:
                    uprice_col = i
                elif cell in _TOTAL_ALIASES:
                    total_col = i

            # Need at least a total column to be useful
            if total_col is None:
                continue

            for row in table[1:]:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                # Skip subtotal/summary rows
                row_text = " ".join(str(c or "") for c in row)
                if _SKIP_ROW_RE.search(row_text):
                    continue
                # Skip rows where all non-desc cells are empty (section headers)
                numeric_cells = [
                    i for i in [qty_col, uprice_col, total_col] if i is not None
                ]
                if numeric_cells and all(
                    row[i] is None or str(row[i]).strip() == "" for i in numeric_cells
                ):
                    continue

                desc = str(row[desc_col]).strip() if desc_col is not None and row[desc_col] else None
                total = parse_amount(str(row[total_col])) if total_col is not None and row[total_col] else None
                qty = parse_amount(str(row[qty_col])) if qty_col is not None and row[qty_col] else None
                unit_price = parse_amount(str(row[uprice_col])) if uprice_col is not None and row[uprice_col] else None

                if total is not None and desc and len(desc) > 2:
                    items.append(
                        ParsedLineItem(
                            description=desc,
                            quantity=qty,
                            unit_price=unit_price,
                            total=total,
                        )
                    )
                elif total is not None:
                    warnings.append(f"low-confidence line item: {desc!r}")

        return items

    def _extract_line_items_regex(self, page_text: str, warnings: list[str]) -> list[ParsedLineItem]:
        items = []
        for line in page_text.splitlines():
            m = re.match(r"^(.+?)\s{2,}(\d[\d,. ]+)$", line.strip())
            if m:
                desc = m.group(1).strip()
                total = parse_amount(m.group(2))
                if total and len(desc) > 2:
                    items.append(ParsedLineItem(description=desc, total=total))
        return items

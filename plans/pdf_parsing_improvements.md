# PDF Invoice Parsing — Improvement Plan

**File under review:** `app/parsers/pdf_invoice.py`
**Supporting files:** `app/parsers/base.py`, `app/parsers/normalizers.py`
**Test fixtures generator:** `test-samples/generate_pdfs.py`
**Existing tests:** `tests/unit/parsers/test_pdf_invoice_parser.py` (2 smoke tests only)

---

## Current State Summary

`PdfInvoiceParser.parse()` (line 11–30) does three things:

1. Calls `page.extract_text()` on every page and joins the results with `"\n"` into a single `full_text` string (lines 14, 18).
2. Runs a series of independent `re.search()` calls on that flat string to extract header fields (lines 22–27).
3. Iterates over each page's text line by line and uses one brittle regex (`r"^(.+?)\s{2,}(\d[\d,. ]+)$"`, line 79) to find line items.

**Known failure modes against the six existing test PDFs:**

| PDF | Known failure |
|---|---|
| `invoice_complete.pdf` | Line item regex captures only description + total; qty and unit\_price are lost (base.ParsedLineItem has those fields, they are never populated) |
| `invoice_multipage.pdf` | Page 2 repeats the vendor/invoice-number header with "(continued)" suffix; parser may return a garbled vendor name; no deduplication of duplicate totals |
| `invoice_non_standard.pdf` | `_extract_vendor` regex doesn't list `"bill\s+from"` before checking the fallback company-name pattern, so the capture from `"Bill From: Sunrise Digital Agency"` requires the first branch; `_extract_invoice_number` doesn't match `"Inv No"` |
| `invoice_euro_format.pdf` | Table headers are German (`"Leistung"`, `"Menge"`, `"Einzelpreis"`, `"Betrag"`); none are matched. `_extract_total` pattern looks for `"total\|amount\s+due\|grand\s+total"` — misses `"Gesamtbetrag / Total"` |
| All PDFs | `extract_text()` flattens multi-column layouts; right-aligned numbers on the same visual row land on different text lines after extraction |

---

## Phase 1 — Structured Table Extraction

**Goal:** Replace the single regex in `_extract_line_items` with pdfplumber's native table API so that all four columns (description, qty, unit price, total) are captured accurately.

**Complexity:** Medium

### Background on the pdfplumber table API

```python
# Per-page structured extraction
with pdfplumber.open(io.BytesIO(data)) as pdf:
    for page in pdf.pages:
        tables = page.extract_tables()           # list[list[list[str|None]]]
        table  = page.extract_table()            # first table only
        # table_settings lets you tune line detection
        tables = page.extract_tables({
            "vertical_strategy":   "lines",      # "lines" | "text" | "explicit"
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "edge_min_length": 10,
            "min_words_vertical": 3,
            "min_words_horizontal": 1,
        })
```

Each cell value is a string or `None` (merged/empty). Row 0 is typically the header row.

### Task checklist

- [ ] **1.1** In `parse()`, switch from `page.extract_text()` to keeping a reference to the open `pdf` object across the full parse (currently the `with` block closes after line 14; line 28 then calls `_extract_line_items(pdf_pages_text=pages_text, ...)` — a text-only list). Refactor to pass the live `pdf.pages` list so later phases can call coordinate APIs.

  **Change in `pdf_invoice.py` lines 13–28:**
  ```python
  # Before (lines 13–18):
  with pdfplumber.open(io.BytesIO(data)) as pdf:
      pages_text = [page.extract_text() or "" for page in pdf.pages]
  full_text = "\n".join(pages_text)
  ...
  result.line_items = self._extract_line_items(pdf_pages_text=pages_text, warnings=warnings)

  # After:
  with pdfplumber.open(io.BytesIO(data)) as pdf:
      pages_text = [page.extract_text() or "" for page in pdf.pages]
      full_text  = "\n".join(pages_text)
      ...header extraction stays the same for now...
      result.line_items = self._extract_line_items(pdf_pages=pdf.pages, warnings=warnings)
  ```

- [ ] **1.2** Write `_extract_line_items_from_table(page, warnings)` that:
  - Calls `page.extract_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"})`.
  - Identifies the header row by checking if any cell matches column name aliases:
    ```python
    DESC_ALIASES  = {"description", "item", "service", "leistung"}
    QTY_ALIASES   = {"qty", "quantity", "menge", "units"}
    UPRICE_ALIASES= {"unit price", "unit", "rate", "einzelpreis", "preis"}
    TOTAL_ALIASES = {"total", "amount", "betrag", "line total"}
    ```
  - Maps column indices from the header row to the four semantic fields.
  - Iterates data rows, calling `parse_amount()` on numeric cells.
  - Returns `list[ParsedLineItem]`.

- [ ] **1.3** Write `_is_data_row(row: list[str | None]) -> bool` to skip non-item rows:
  - Subtotal/total rows: any cell matches `r"^\s*(sub.?total|grand total|gesamtbetrag)\s*$"` (case-insensitive).
  - Section header rows: all numeric cells are `None` or empty.
  - Empty rows: all cells are `None`.

- [ ] **1.4** Implement **confidence scoring** per row:
  ```python
  @dataclass
  class ScoredLineItem:
      item: ParsedLineItem
      confidence: float          # 0.0–1.0
      confidence_notes: list[str]
  ```
  Rules:
  - `description` present and `len > 3`: +0.3
  - `total` parses cleanly to `Decimal`: +0.4
  - `qty` and `unit_price` both present and `qty * unit_price ≈ total` (within 1%): +0.3
  - Any cell in the row is `None` when the column was found in the header: −0.2 per missing cell
  - Row `confidence < 0.5` → append to `warnings` as `"low-confidence line item: {description!r}"` and still include the item (caller decides whether to reject it).

- [ ] **1.5** Handle **merged cells and subtotal rows**:
  - A cell spanning multiple columns appears as a non-`None` value in one column and `None` in the rest of the same row. Detect this by checking that numeric columns are all `None` while description is non-empty — treat the row as a section header (skip for line items).
  - Subtotal rows are skipped by `_is_data_row` above.

- [ ] **1.6** Update `_extract_line_items` to try structured extraction first and fall back to the regex path (Phase 4 will improve the fallback):
  ```python
  def _extract_line_items(self, pdf_pages, warnings):
      items = []
      for page in pdf_pages:
          table_items = self._extract_line_items_from_table(page, warnings)
          if table_items:
              items.extend(table_items)
          else:
              # existing regex fallback on page.extract_text()
              items.extend(self._extract_line_items_regex(page.extract_text() or "", warnings))
      return items
  ```

**Files to create or modify:**
- Modify: `app/parsers/pdf_invoice.py`
- Create: `app/parsers/_table_utils.py` — column-alias matching and `_is_data_row` logic (keeps the main parser readable)

**Deliverable:** `_extract_line_items` correctly populates `quantity`, `unit_price`, and `total` for all four invoices that use bordered tables (`invoice_complete.pdf`, `invoice_partial.pdf`, `invoice_multipage.pdf`, `invoice_non_standard.pdf`). The `ScoredLineItem` confidence gate emits warnings for rows missing qty/unit\_price.

---

## Phase 2 — Robust Header Field Extraction

**Goal:** Replace the seven independent regex calls (lines 22–27) with a label-anchor approach that is resilient to varied formatting and expanded label vocabularies.

**Complexity:** Medium

### The label-anchor approach

Instead of scanning the full text string for a combined label+value pattern, the approach is:
1. Extract all `(x0, top, text)` word objects from the page using `page.extract_words()`.
2. Find words that match a known label alias (e.g. `"Invoice Date"`).
3. The value is whichever word object sits immediately to the right on the same line (`top` within ±4px) or on the next line directly below (`x0` within ±20px of the label's `x0`).

```python
# pdfplumber word object shape:
# {"text": "Invoice", "x0": 12.3, "top": 45.1, "x1": 55.2, "bottom": 56.0, ...}
words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
```

### Expanded label alias dictionary

```python
LABEL_ALIASES: dict[str, list[str]] = {
    "vendor_name": [
        "vendor", "from", "bill from", "biller", "sold by",
        "issued by", "supplier", "service provider",
    ],
    "invoice_number": [
        "invoice #", "invoice no", "invoice number",
        "inv #", "inv no", "inv.", "reference", "ref #",
    ],
    "invoice_date": [
        "invoice date", "date", "issue date", "dated",
        "billing date", "billed on",
    ],
    "due_date": [
        "due date", "payment due", "pay by", "due by",
        "payment terms",           # value will be "Net 30" — needs fiscal-period handling
    ],
    "total_amount": [
        "total", "grand total", "amount due", "total due",
        "balance due", "net payable",
        "gesamtbetrag",            # German
        "montant total",           # French
    ],
    "tax_amount": [
        "tax", "vat", "gst", "hst", "sales tax",
        "mwst", "mwst.", "ust",    # German VAT abbreviations
    ],
}
```

### Task checklist

- [ ] **2.1** Write `_find_label_anchor(words, aliases) -> str | None` in a new `_header_utils.py`:
  - Normalise each word's text to lowercase, strip punctuation.
  - Slide a window of 1–3 consecutive words to match multi-word labels (e.g. "Invoice Date").
  - When a match is found, collect all words on the same line to the right as the raw value string.
  - If no same-line value exists, collect the next line's words at approximately the same x0.
  - Return the joined value string, or `None`.

- [ ] **2.2** Refactor `_extract_vendor`:
  - Use label-anchor search first (labels: `"vendor"`, `"bill from"`, etc.).
  - The raw value from `"Bill From"` in `invoice_complete.pdf` is `"Acme Corp, 123 Main St, San Francisco, CA 94105"` — strip everything from the first comma that follows a non-numeric character: `re.split(r",\s*(?!\d)", value, maxsplit=1)[0]`.
  - For multi-line addresses (value is empty on the label line, value is on the next line), the anchor approach already handles this — the next-line fallback returns the first line of the address block.
  - Keep the company-name fallback regex (current line 35) as a last resort.

- [ ] **2.3** Refactor `_extract_invoice_number`:
  - Current pattern (line 51) misses `"Inv No"`. Add all aliases from the dictionary above.
  - The value must match `r"[A-Z0-9][A-Z0-9\-/]{2,}"` — reject pure English words that happen to follow a label.

- [ ] **2.4** Refactor `_extract_date` to handle more formats:
  - `"15.09.2024"` — already handled by `dateutil` with `dayfirst=True` (normalizers.py line 18).
  - `"Net 30"` / `"Net 15"` — fiscal period; compute `invoice_date + timedelta(days=30)` and set `due_date`. Add warning `"due_date derived from payment terms: Net 30"`.
  - `"Q3 2024"` / `"FY2024-Q1"` — set to the last day of the period; add warning.
  - Relative: `"30 days from invoice date"` — same as Net 30 derivation above.

- [ ] **2.5** Refactor `_extract_total` to handle German/multilingual labels:
  - Add `"gesamtbetrag"` and `"montant total"` to the search pattern.
  - The `"Gesamtbetrag / Total:"` line in `invoice_euro_format.pdf` currently fails because the pipe character breaks the regex match boundary. The label-anchor approach resolves this naturally.

- [ ] **2.6** Handle two-column layout (labels on left, values on right, no border):
  - Detect by checking that the page has two dominant x-coordinate clusters of words (left column x0 < page width/2, right column x0 > page width/2).
  - In this mode, treat every left-column word as a potential label and search the right column at the same `top` for the value.
  - The `kv()` helper in `generate_pdfs.py` (line 37–41) produces exactly this layout: label cell width 50, value fills the rest.

**Files to create or modify:**
- Modify: `app/parsers/pdf_invoice.py`
- Create: `app/parsers/_header_utils.py` — label-anchor word search, alias dictionary
- Modify: `app/parsers/normalizers.py` — add fiscal-period date handling to `parse_date()`

**Deliverable:** All six test PDFs extract `vendor_name`, `invoice_number`, `invoice_date`, `due_date`, `total_amount`, and `tax_amount` without warnings (except `invoice_partial.pdf` which intentionally omits vendor and due date). `invoice_non_standard.pdf` resolves `"Inv No"` and `"Amount Due"` correctly. `invoice_euro_format.pdf` resolves `"Gesamtbetrag / Total"`.

---

## Phase 3 — Multi-Page Intelligence

**Goal:** Detect the role of each page, carry header fields from the cover page, accumulate line items across all pages, and suppress duplicate totals and repeated continuation headers.

**Complexity:** High

### Current behaviour (lines 13–28)

All pages are joined into `full_text` before any parsing. The header regexes run on this blob, so they can accidentally match the repeated header on page 2 of `invoice_multipage.pdf` (`"GT-2024-0188 (continued)"`). Line items are accumulated page by page but there is no awareness of continuation markers.

### Page role detection

```python
class PageRole(enum.Enum):
    COVER      = "cover"        # first page with header fields
    LINE_ITEMS = "line_items"   # contains a line items table
    SUMMARY    = "summary"      # subtotals / grand total only
    CONTINUATION = "continuation"  # subsequent pages of the same invoice
    UNKNOWN    = "unknown"
```

Detection rules (applied in order, first match wins):

1. **COVER**: page index == 0, OR page contains two or more header field labels from the alias dictionary.
2. **CONTINUATION**: page text matches `r"continued\s+from\s+previous|page\s+\d+\s+of\s+\d+"` (case-insensitive), OR the page header repeats the same invoice number as page 1 followed by `"(continued)"`.
3. **LINE\_ITEMS**: `page.extract_tables()` returns at least one table with ≥ 2 data rows that pass `_is_data_row`.
4. **SUMMARY**: page contains no table or a table with ≤ 1 data row, but contains a total/grand-total label.
5. **UNKNOWN**: anything else.

### Task checklist

- [ ] **3.1** Write `_detect_page_role(page, page_index, known_invoice_number) -> PageRole` using the rules above. Place in `app/parsers/_page_utils.py`.

- [ ] **3.2** Refactor `parse()` to process pages in role order:
  ```python
  with pdfplumber.open(io.BytesIO(data)) as pdf:
      roles = [
          self._detect_page_role(page, i, known_invoice_number=None)
          for i, page in enumerate(pdf.pages)
      ]
      # First pass: extract header fields from COVER pages only
      cover_text = "\n".join(
          page.extract_text() or ""
          for page, role in zip(pdf.pages, roles)
          if role in (PageRole.COVER, PageRole.UNKNOWN)
      )
      # Extract headers from cover_text (Phase 2 methods)
      ...
      # Second pass: accumulate line items from LINE_ITEMS + CONTINUATION pages
      for page, role in zip(pdf.pages, roles):
          if role in (PageRole.LINE_ITEMS, PageRole.CONTINUATION, PageRole.COVER):
              items.extend(self._extract_line_items_from_table(page, warnings))
      # Third pass: extract totals from SUMMARY page (or COVER if no SUMMARY page)
      ...
  ```

- [ ] **3.3** Suppress duplicate headers on continuation pages:
  - After Phase 2 extracts `invoice_number` from the cover page, store it.
  - On CONTINUATION pages, call `_extract_line_items_from_table` only — do not re-run header extraction.
  - Strip any repeated occurrence of `invoice_number + r"\s*\(continued\)"` from the extracted text before field extraction.

- [ ] **3.4** Suppress duplicate totals:
  - SUMMARY page totals are authoritative. If a SUMMARY page is found, do not extract `total_amount` from COVER or LINE\_ITEMS pages.
  - If no SUMMARY page, use the last occurrence of a total label in `full_text` (current behaviour works for single-page invoices; for multi-page, last-occurrence is better than first-occurrence since the real grand total is at the end).
  - In `invoice_multipage.pdf`, the `"Grand Total: $45,342.00"` is on page 2 (SUMMARY). The subtotals within each page's table should not be mistaken for the invoice total.

- [ ] **3.5** Add `page_roles: list[str]` to `InvoiceParseResult` (in `base.py`) as a diagnostic field so callers can inspect role assignment.

**Files to create or modify:**
- Modify: `app/parsers/pdf_invoice.py`
- Create: `app/parsers/_page_utils.py`
- Modify: `app/parsers/base.py` — add `page_roles` field to `InvoiceParseResult`

**Deliverable:** `invoice_multipage.pdf` extracts `vendor_name = "GlobalTech Solutions Ltd"` (not the continuation variant), `invoice_number = "GT-2024-0188"` (without `"(continued)"`), all 11 line items across both pages, and `total_amount = 45342.00` from the SUMMARY page only.

---

## Phase 4 — Layout-Aware Fallbacks

**Goal:** When `extract_tables()` returns nothing (no ruled lines, no clear column borders), use pdfplumber's word-coordinate API to infer column structure from x-position clustering.

**Complexity:** High

### When this triggers

Invoices generated without cell borders (e.g. a plain-text invoice, `invoice_minimal.pdf`, or some real-world vendor invoices produced by accounting software that uses whitespace-only alignment) return an empty list from `extract_tables()`. The current regex fallback (line 79) captures at most two fields.

### Coordinate-based column detection

```python
words = page.extract_words(x_tolerance=3, y_tolerance=3)
# Each word: {"text": ..., "x0": float, "top": float, "x1": float, "bottom": float}

# 1. Collect all x0 values from words that look like numbers (line item amounts)
# 2. Cluster by proximity (gap > 10px = new cluster)
# 3. Identify column bands: leftmost = description, rightmost = total,
#    second-from-right = unit_price, third-from-right = qty (if present)
```

Concretely, for a table with four columns at x0 ≈ [10, 100, 135, 165]:

```python
def _infer_column_bands(words: list[dict]) -> list[tuple[float, float]]:
    """Return (x_min, x_max) bands for each inferred column, left to right."""
    x0s = sorted({round(w["x0"]) for w in words})
    bands, current_start = [], x0s[0]
    for prev, curr in zip(x0s, x0s[1:]):
        if curr - prev > 12:          # gap threshold
            bands.append((current_start, prev + 10))
            current_start = curr
    bands.append((current_start, x0s[-1] + 10))
    return bands
```

### Task checklist

- [ ] **4.1** Write `_group_words_into_rows(words) -> list[list[dict]]`:
  - Group words that share a `top` value within ±3px into a single row.
  - Sort groups by `top` (ascending = top of page first).

- [ ] **4.2** Write `_assign_words_to_columns(rows, bands) -> list[list[str]]`:
  - For each row, bucket each word into the band whose x-range contains the word's `x0`.
  - Concatenate words within the same band (in left-to-right order) to form a cell string.
  - Return a list of rows, each row being a list of cell strings aligned to `bands`.

- [ ] **4.3** Write `_extract_line_items_coordinate_fallback(page, warnings) -> list[ParsedLineItem]`:
  - Calls `_infer_column_bands`, `_group_words_into_rows`, `_assign_words_to_columns`.
  - Identifies header row (first row where any cell matches a column alias from Phase 1's alias sets).
  - Iterates data rows through Phase 1's `_is_data_row` filter and confidence scoring.
  - Returns `list[ParsedLineItem]`.

- [ ] **4.4** Integrate into `_extract_line_items` as the second fallback (after the Phase 1 table extraction, before the Phase 1 regex):
  ```python
  table_items = self._extract_line_items_from_table(page, warnings)
  if table_items:
      return table_items
  coord_items = self._extract_line_items_coordinate_fallback(page, warnings)
  if coord_items:
      return coord_items
  return self._extract_line_items_regex(page.extract_text() or "", warnings)
  ```

- [ ] **4.5** Use font metadata as a signal:
  - `page.extract_words(extra_attrs=["fontname", "size"])` returns font info per word.
  - Bold font (`"fontname"` contains `"Bold"` or `"B"` suffix) → treat the row as a header or label, not a data row.
  - Larger font size (> median size on the page by ≥ 2pt) → likely a section heading, skip as line item.
  - Add this check inside `_is_data_row`.

**Files to create or modify:**
- Modify: `app/parsers/pdf_invoice.py`
- Create: `app/parsers/_coord_utils.py` — column-band inference, word-row grouping, coordinate-based extraction

**Deliverable:** `invoice_minimal.pdf` (which has no tables at all, just `multi_cell` free text) extracts `total_amount = 875.00` via the coordinate fallback rather than pure regex. New test PDFs without cell borders (see Phase 5) parse correctly for description and total columns.

---

## Phase 5 — Test Fixtures and Regression Suite

**Goal:** Replace the two smoke tests in `test_pdf_invoice_parser.py` with a comprehensive parametrized suite covering every extraction path, and establish a regression workflow for new invoice formats.

**Complexity:** Low–Medium

### New test PDF fixtures to create

Add the following generators to `test-samples/generate_pdfs.py`:

| Function | File | What it covers |
|---|---|---|
| `invoice_no_borders()` | `invoice_no_borders.pdf` | Table uses whitespace alignment only — forces coordinate fallback (Phase 4) |
| `invoice_two_column_layout()` | `invoice_two_column_layout.pdf` | All header fields in a two-column label/value grid (no `"Vendor:"` prefix) |
| `invoice_continuation_markers()` | `invoice_continuation_markers.pdf` | 3 pages; pages 2–3 start with `"Continued from previous page"` — tests Phase 3 continuation suppression |
| `invoice_net30_due_date()` | `invoice_net30_due_date.pdf` | Due date written as `"Net 30"` — tests fiscal-period date derivation (Phase 2.4) |
| `invoice_merged_cells()` | `invoice_merged_cells.pdf` | Table has a section header row spanning all columns between two groups of line items |
| `invoice_german_only()` | `invoice_german_only.pdf` | All labels in German only (no English fallback) — extends `invoice_euro_format.pdf` scenario |

### Parametrized pytest structure

Create `tests/unit/parsers/test_pdf_invoice_parser_parametrized.py`:

```python
import pytest
from decimal import Decimal
from pathlib import Path
from app.parsers.pdf_invoice import PdfInvoiceParser

SAMPLES = Path(__file__).parent.parent.parent.parent / "test-samples"

CASES = [
    pytest.param(
        "invoice_complete.pdf",
        {
            "vendor_name":     "Acme Corp",
            "invoice_number":  "INV-2024-0042",
            "invoice_date":    date(2024, 3, 15),
            "due_date":        date(2024, 4, 15),
            "total_amount":    Decimal("12694.50"),
            "tax_amount":      Decimal("994.50"),
            "currency":        "USD",
            "line_item_count": 4,
        },
        set(),          # expected warnings (empty = none)
        id="complete",
    ),
    pytest.param(
        "invoice_partial.pdf",
        {
            "vendor_name":    None,
            "invoice_number": "INV-2024-0099",
            "due_date":       None,
            "total_amount":   Decimal("2350.00"),
        },
        {"vendor_name not found", "due date not found"},
        id="partial",
    ),
    pytest.param(
        "invoice_minimal.pdf",
        {
            "vendor_name":   None,
            "total_amount":  Decimal("875.00"),
            "invoice_date":  date(2024, 6, 15),
        },
        {"vendor_name not found", "invoice_number not found", "due date not found"},
        id="minimal",
    ),
    pytest.param(
        "invoice_multipage.pdf",
        {
            "vendor_name":     "GlobalTech Solutions Ltd",
            "invoice_number":  "GT-2024-0188",
            "total_amount":    Decimal("45342.00"),
            "tax_amount":      Decimal("4122.00"),
            "line_item_count": 11,
        },
        set(),
        id="multipage",
    ),
    pytest.param(
        "invoice_non_standard.pdf",
        {
            "vendor_name":    "Sunrise Digital Agency",
            "invoice_number": "SDA-9901",
            "total_amount":   Decimal("5092.50"),
            "tax_amount":     Decimal("242.50"),
            "currency":       "USD",
        },
        set(),
        id="non_standard",
    ),
    pytest.param(
        "invoice_euro_format.pdf",
        {
            "vendor_name":    "Muster GmbH",
            "invoice_number": "RG-2024-0077",
            "total_amount":   Decimal("152617.50"),
            "tax_amount":     Decimal("24367.50"),
            "currency":       "EUR",
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
    data = path.read_bytes()
    result = PdfInvoiceParser().parse(data)

    for field, expected in expected_fields.items():
        if field == "line_item_count":
            assert len(result.line_items) == expected, (
                f"{pdf_name}: expected {expected} line items, got {len(result.line_items)}"
            )
        else:
            assert getattr(result, field) == expected, (
                f"{pdf_name}: {field} expected {expected!r}, got {getattr(result, field)!r}"
            )

    actual_warnings = set(result.parse_warnings)
    assert actual_warnings == expected_warnings, (
        f"{pdf_name}: warnings mismatch\n  expected: {expected_warnings}\n  actual:   {actual_warnings}"
    )
```

### Extraction accuracy measurement

Add a pytest fixture `extraction_accuracy` that computes a per-field accuracy score across all parametrized cases:

```python
# conftest.py addition (tests/unit/parsers/conftest.py)
@pytest.fixture(scope="session", autouse=True)
def extraction_accuracy(request):
    yield   # let tests run
    # After session: read results from the stash and print accuracy table
    # (Hook into pytest_terminal_summary or use a plugin)
```

Alternatively, add a standalone script `tests/tools/measure_accuracy.py` that:
1. Runs all parametrized cases.
2. For each field in `expected_fields`, scores 1.0 if exact match, 0.0 if mismatch, 0.5 if expected is non-None but result is None (extraction failure vs wrong value).
3. Prints a table:
   ```
   Field            Pass    Fail    Skip    Accuracy
   vendor_name        5       0       1       100%
   invoice_number     6       0       0       100%
   total_amount       6       0       0       100%
   ...
   ```

### Regression workflow for new invoice formats

When a new invoice format causes extraction to fail:

1. Drop the failing PDF into `test-samples/` (name it `invoice_regression_<issue-id>.pdf`).
2. Add a `pytest.param` entry to `CASES` with the expected field values (can be partially filled — use `None` for unknown fields during investigation).
3. Run `pytest tests/unit/parsers/test_pdf_invoice_parser_parametrized.py -k regression` to confirm failure.
4. Fix the parser.
5. Confirm the regression test passes and all existing tests still pass.
6. The PDF fixture stays in the repo permanently — it is now a guard against regression.

For PDFs that cannot be committed (confidential client data), create a synthetic lookalike using the `generate_pdfs.py` pattern that reproduces the structural layout without real data.

**Files to create or modify:**
- Modify: `test-samples/generate_pdfs.py` — add six new generator functions
- Create: `tests/unit/parsers/test_pdf_invoice_parser_parametrized.py`
- Create: `tests/tools/measure_accuracy.py`
- Modify: `tests/unit/parsers/conftest.py` (if it doesn't exist, create it)

**Deliverable:** Running `pytest tests/unit/parsers/` produces ≥ 6 parametrized test cases with named IDs. The accuracy script reports field-level pass rates. Adding a new regression PDF requires only two steps (drop file, add `pytest.param`).

---

## Implementation Order and Dependencies

```
Phase 1 (table extraction)
    └── required by Phase 3 (per-page processing needs structured rows)
    └── required by Phase 4 (fallback only makes sense once primary is solid)

Phase 2 (header extraction)
    └── can be done in parallel with Phase 1
    └── required by Phase 3 (cover-page header fields need the label-anchor approach)

Phase 3 (multi-page)
    └── depends on Phase 1 and Phase 2

Phase 4 (coordinate fallback)
    └── depends on Phase 1 (replaces the regex fallback at the bottom of the chain)

Phase 5 (test suite)
    └── write fixture stubs before Phase 1 (TDD); fill in expected values as phases land
    └── final accuracy script after Phase 4
```

## Complexity and Effort Summary

| Phase | Complexity | New files | Key pdfplumber APIs used |
|---|---|---|---|
| 1 — Structured table extraction | Medium | `_table_utils.py` | `page.extract_tables()`, `extract_table()` |
| 2 — Robust header extraction | Medium | `_header_utils.py` | `page.extract_words()` |
| 3 — Multi-page intelligence | High | `_page_utils.py` | `page.extract_text()`, `extract_words()` |
| 4 — Coordinate fallback | High | `_coord_utils.py` | `page.extract_words(extra_attrs=["fontname","size"])` |
| 5 — Test fixtures and suite | Low–Medium | `test_pdf_invoice_parser_parametrized.py`, `measure_accuracy.py` | — |

## Files Modified Across All Phases

| File | Change |
|---|---|
| `app/parsers/pdf_invoice.py` | Refactored throughout; all private methods replaced or extended |
| `app/parsers/base.py` | Add `page_roles: list[str]` to `InvoiceParseResult` |
| `app/parsers/normalizers.py` | Add fiscal-period date handling to `parse_date()` |
| `app/parsers/_table_utils.py` | New — column alias matching, `_is_data_row`, `ScoredLineItem` |
| `app/parsers/_header_utils.py` | New — `LABEL_ALIASES` dict, `_find_label_anchor()` |
| `app/parsers/_page_utils.py` | New — `PageRole` enum, `_detect_page_role()` |
| `app/parsers/_coord_utils.py` | New — column-band inference, word-row grouping |
| `test-samples/generate_pdfs.py` | Add six new invoice generators |
| `tests/unit/parsers/test_pdf_invoice_parser_parametrized.py` | New — full parametrized suite |
| `tests/tools/measure_accuracy.py` | New — field-level accuracy reporting |

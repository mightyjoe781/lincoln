# UI Plan — Lincoln Dashboard

A minimal, clean single-page interface for uploading documents and browsing extracted data.
No frameworks beyond plain HTML + vanilla JS (or optionally Vite + React if preferred).
Served statically from the FastAPI app itself — no separate deployment.

---

## Goals

- Upload PDF invoices and CSV bank statements via drag-and-drop or file picker
- See processing status in real time (polling)
- Browse extracted invoices and transactions with basic filtering
- Delete documents
- No build step required for the minimal version

---

## Stack

| Layer     | Choice                                         |
|-----------|------------------------------------------------|
| Markup    | HTML5                                          |
| Styling   | Tailwind CSS (CDN, no build step)              |
| JS        | Vanilla ES modules (no framework)              |
| Served by | FastAPI `StaticFiles` mounted at `/`           |
| API       | Existing `/api/v1` endpoints                   |

---

## Directory Structure

```
lincoln/
└── ui/
    ├── index.html          # single page, tab-based layout
    ├── app.js              # all JS — upload, polling, list, delete
    └── style.css           # minimal overrides on top of Tailwind
```

FastAPI mount (add to `app/main.py`):
```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")
```

---

## Layout — Three Tabs

```
┌─────────────────────────────────────────────────┐
│  Lincoln  [Upload]  [Invoices]  [Transactions]  │
├─────────────────────────────────────────────────┤
│                                                 │
│            (active tab content)                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## Tab 1 — Upload

```
┌──────────────────────────────────────────┐
│  Drop PDF or CSV here, or click to browse │
│                                          │
│            [Choose File]                 │
└──────────────────────────────────────────┘

Recent Uploads
┌──────┬─────────────┬──────────┬────────┬─────────┐
│ Name │ Type        │ Status   │ Size   │ Actions │
├──────┼─────────────┼──────────┼────────┼─────────┤
│ ...  │ pdf_invoice │ ● done   │ 42 KB  │ Delete  │
│ ...  │ csv_stmt    │ ○ failed │ 8 KB   │ Delete  │
└──────┴─────────────┴──────────┴────────┴─────────┘
```

**Behaviour:**
- Drag-and-drop or click triggers `POST /api/v1/documents/upload`
- Upload button shows spinner while in flight
- On 201: add row with `status=processing`, poll `GET /documents/{id}` every 2 s until `done` or `failed`
- Status badge: green dot (done), red dot (failed), yellow dot (processing)
- Duplicate upload: show "Already uploaded — returning existing record" toast
- File too large / wrong type: show inline error, no request sent

---

## Tab 2 — Invoices

```
Filter: [Vendor ________] [From ____] [To ____] [Currency ___] [Apply]

┌──────────────┬─────────────┬──────────┬───────────┬──────────┬─────────┐
│ Vendor       │ Invoice #   │ Date     │ Due Date  │ Total    │ Actions │
├──────────────┼─────────────┼──────────┼───────────┼──────────┼─────────┤
│ Acme Corp    │ INV-0042    │ 2024-03  │ 2024-04   │ $12,694  │ View    │
└──────────────┴─────────────┴──────────┴───────────┴──────────┴─────────┘

[← Prev]  Page 1 of 3  [Next →]
```

**Behaviour:**
- On tab open: `GET /api/v1/invoices?page=1&page_size=20`
- Filter inputs debounce 400 ms then re-fetch
- Click **View** → slide-in panel showing all fields + line items table
- Line items table: Description / Qty / Unit Price / Total
- Empty state: "No invoices yet — upload a PDF invoice to get started"

---

## Tab 3 — Transactions

```
Filter: [Description ________] [From ____] [To ____] [Currency ___] [Apply]

┌─────────────┬─────────────────────┬──────────┬──────────┬──────────┐
│ Date        │ Description         │ Amount   │ Currency │ D/C      │
├─────────────┼─────────────────────┼──────────┼──────────┼──────────┤
│ 2024-04-02  │ Salary April 2024   │ 6,000.00 │ USD      │ Credit   │
│ 2024-04-03  │ Rent Q2 2024        │ 2,000.00 │ USD      │ Debit    │
└─────────────┴─────────────────────┴──────────┴──────────┴──────────┘

[← Prev]  Page 1 of 2  [Next →]
```

**Behaviour:**
- Same pattern as Invoices tab
- Debit rows: red amount; Credit rows: green amount
- No detail panel needed (transactions have no nested data)

---

## Implementation Tasks

### Phase UI-0 — Scaffold
- [ ] Create `ui/index.html` with Tailwind CDN, three tab buttons, tab panel containers
- [ ] `ui/app.js` — tab switching logic, `API_BASE = "/api/v1"` constant
- [ ] Mount `StaticFiles` in `app/main.py` (add `python-multipart` already present, add `aiofiles` already present)
- [ ] Verify `GET /` serves the page

### Phase UI-1 — Upload Tab
- [ ] Drag-and-drop zone (dragover / drop events, highlight on drag)
- [ ] File input fallback (`<input type="file" accept=".pdf,.csv">`)
- [ ] `uploadFile(file)` — `FormData` + `fetch POST /api/v1/documents/upload`
- [ ] Response handling: 201 (new), 200 (duplicate), 413 (too large), 422 (wrong type)
- [ ] Toast notification component (auto-dismiss 4 s)
- [ ] `pollStatus(documentId)` — `setInterval` 2 s, clears when `done`/`failed`
- [ ] Render recent uploads table from `GET /api/v1/documents`
- [ ] Delete button → `DELETE /api/v1/documents/{id}`, remove row

### Phase UI-2 — Invoices Tab
- [ ] `fetchInvoices(params)` — builds query string from filter state, fetches, renders table
- [ ] Filter form with vendor, date_from, date_to, currency inputs
- [ ] Pagination controls (prev/next, page indicator)
- [ ] Detail panel: slide-in `<aside>`, populated from `GET /api/v1/invoices/{id}`
- [ ] Line items nested table inside detail panel
- [ ] Close panel on Escape or backdrop click

### Phase UI-3 — Transactions Tab
- [ ] `fetchTransactions(params)` — same pattern as invoices
- [ ] Filter form (description, date range, currency)
- [ ] Debit/credit colour coding
- [ ] Pagination controls

### Phase UI-4 — Polish
- [ ] Loading skeleton rows while fetching (prevents layout shift)
- [ ] Empty state illustrations (simple SVG or text)
- [ ] Responsive: single-column on narrow viewports
- [ ] Favicon (simple `L` letter)
- [ ] Page title: "Lincoln — Financial Document Parser"

---

## API Calls Summary

| Action                  | Endpoint                                 |
|-------------------------|------------------------------------------|
| Upload file             | `POST /api/v1/documents/upload`          |
| List documents          | `GET /api/v1/documents`                  |
| Poll document status    | `GET /api/v1/documents/{id}`             |
| Delete document         | `DELETE /api/v1/documents/{id}`          |
| List invoices           | `GET /api/v1/invoices?vendor_name=&...`  |
| Get invoice + items     | `GET /api/v1/invoices/{id}`              |
| List transactions       | `GET /api/v1/transactions?...`           |

---

## What This UI Is Not

- Not a full React/Next.js app — no build step, no bundler, no TypeScript
- Not mobile-first — responsive enough for laptop/desktop use
- Not authenticated — assumes local or trusted internal use (add auth header logic if JWT bonus is implemented)
- Not a replacement for `/docs` (Swagger) — that remains available at `/docs` for API exploration

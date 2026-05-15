// Lincoln UI — vanilla ES modules

const API_BASE = "/api/v1";

// ── Utilities ──────────────────────────────────────────────────────────────

function fmt(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 ** 2).toFixed(1) + " MB";
}

function fmtNum(val) {
  if (val == null) return "—";
  return Number(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(val) {
  if (!val) return "—";
  return val.slice(0, 10);
}

function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v != null) p.set(k, v);
  }
  return p.toString() ? "?" + p.toString() : "";
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(API_BASE + path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw Object.assign(new Error(detail), { status: res.status });
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── Toasts ─────────────────────────────────────────────────────────────────

const toastContainer = document.getElementById("toast-container");

function toast(msg, type = "info") {
  const colors = {
    info:    "bg-gray-800 text-white",
    success: "bg-green-600 text-white",
    error:   "bg-red-600 text-white",
    warn:    "bg-yellow-500 text-white",
  };
  const el = document.createElement("div");
  el.className = `${colors[type]} text-sm px-4 py-2.5 rounded-lg shadow-lg max-w-sm opacity-0 transition-opacity duration-200`;
  el.textContent = msg;
  toastContainer.appendChild(el);
  requestAnimationFrame(() => { el.style.opacity = "1"; });
  setTimeout(() => {
    el.style.opacity = "0";
    el.addEventListener("transitionend", () => el.remove());
  }, 4000);
}

// ── Tab switching ──────────────────────────────────────────────────────────

const tabBtns = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");

function activateTab(name) {
  tabBtns.forEach(b => {
    const active = b.dataset.tab === name;
    b.classList.toggle("bg-blue-50", active);
    b.classList.toggle("text-blue-700", active);
    b.classList.toggle("text-gray-600", !active);
  });
  tabPanels.forEach(p => p.classList.toggle("hidden", p.id !== "tab-" + name));
  if (name === "upload") loadDocuments();
  if (name === "invoices") { invPage = 1; fetchInvoices(); }
  if (name === "transactions") { txnPage = 1; fetchTransactions(); }
}

document.getElementById("tab-nav").addEventListener("click", e => {
  const btn = e.target.closest(".tab-btn");
  if (btn) activateTab(btn.dataset.tab);
});

// ── Status badge ───────────────────────────────────────────────────────────

function statusBadge(status) {
  const map = {
    done:       { dot: "dot-done",       label: "Done" },
    processing: { dot: "dot-processing", label: "Processing" },
    failed:     { dot: "dot-failed",     label: "Failed" },
  };
  const s = map[status] ?? { dot: "dot-processing", label: status };
  return `<span class="inline-flex items-center gap-1.5">
    <span class="inline-block h-2 w-2 rounded-full ${s.dot}"></span>
    <span class="text-gray-600">${s.label}</span>
  </span>`;
}

// ── Skeleton rows ──────────────────────────────────────────────────────────

function skeletonRows(tbody, cols) {
  tbody.innerHTML = Array.from({ length: 4 }, () =>
    `<tr>${Array.from({ length: cols }, () =>
      `<td class="px-5 py-3"><div class="skeleton h-4 w-full rounded"></div></td>`
    ).join("")}</tr>`
  ).join("");
}

// ── UPLOAD TAB ─────────────────────────────────────────────────────────────

const dropZone    = document.getElementById("drop-zone");
const fileInput   = document.getElementById("file-input");
const dropError   = document.getElementById("drop-error");
const docsTbody   = document.getElementById("docs-tbody");
const docsEmpty   = document.getElementById("docs-empty");
const pollTimers  = {};
const ALLOWED_TYPES = ["application/pdf", "text/csv"];
const MAX_BYTES = 20 * 1024 * 1024; // 20 MB client-side guard

function showDropError(msg) {
  dropError.textContent = msg;
  dropError.classList.remove("hidden");
  setTimeout(() => dropError.classList.add("hidden"), 5000);
}

function validateFile(file) {
  if (!ALLOWED_TYPES.includes(file.type) &&
      !file.name.endsWith(".pdf") && !file.name.endsWith(".csv")) {
    showDropError("Only PDF and CSV files are supported.");
    return false;
  }
  if (file.size > MAX_BYTES) {
    showDropError(`File too large (max 20 MB). Your file is ${fmt(file.size)}.`);
    return false;
  }
  return true;
}

dropZone.addEventListener("dragover", e => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", e => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) handleUpload(file);
});
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) handleUpload(file);
  fileInput.value = "";
});
document.getElementById("refresh-docs").addEventListener("click", loadDocuments);

async function handleUpload(file) {
  if (!validateFile(file)) return;
  dropError.classList.add("hidden");

  const fd = new FormData();
  fd.append("file", file);

  let doc;
  try {
    const res = await fetch(API_BASE + "/documents/upload", { method: "POST", body: fd });
    doc = await res.json();
    if (res.status === 200) {
      toast("Already uploaded — returning existing record.", "warn");
    } else if (res.status === 201) {
      toast("Upload started!", "success");
    } else {
      toast(doc.detail ?? "Upload failed.", "error");
      return;
    }
  } catch {
    toast("Network error during upload.", "error");
    return;
  }

  upsertDocRow(doc);
  if (doc.status === "processing") startPoll(doc.id);
}

function upsertDocRow(doc) {
  docsEmpty.classList.add("hidden");
  let row = docsTbody.querySelector(`tr[data-id="${doc.id}"]`);
  if (!row) {
    row = document.createElement("tr");
    row.dataset.id = doc.id;
    row.className = "hover:bg-gray-50";
    docsTbody.prepend(row);
  }
  row.innerHTML = `
    <td class="px-5 py-3 font-medium text-gray-800 max-w-xs truncate" title="${doc.original_name}">${doc.original_name}</td>
    <td class="px-5 py-3 text-gray-500">${doc.file_type}</td>
    <td class="px-5 py-3">${statusBadge(doc.status)}</td>
    <td class="px-5 py-3 text-gray-500">${fmt(doc.file_size)}</td>
    <td class="px-5 py-3">
      <button class="text-red-500 hover:text-red-700 text-sm font-medium" data-delete="${doc.id}">Delete</button>
    </td>
  `;
}

async function loadDocuments() {
  skeletonRows(docsTbody, 5);
  docsEmpty.classList.add("hidden");
  try {
    const data = await apiFetch("/documents?page=1&page_size=50");
    docsTbody.innerHTML = "";
    if (data.items.length === 0) {
      docsEmpty.classList.remove("hidden");
      return;
    }
    data.items.forEach(upsertDocRow);
    data.items.filter(d => d.status === "processing").forEach(d => startPoll(d.id));
  } catch {
    toast("Failed to load documents.", "error");
    docsTbody.innerHTML = "";
    docsEmpty.classList.remove("hidden");
  }
}

function startPoll(docId) {
  if (pollTimers[docId]) return;
  pollTimers[docId] = setInterval(async () => {
    try {
      const doc = await apiFetch(`/documents/${docId}`);
      upsertDocRow(doc);
      if (doc.status === "done" || doc.status === "failed") {
        clearInterval(pollTimers[docId]);
        delete pollTimers[docId];
        if (doc.status === "failed") toast(`Processing failed: ${doc.original_name}`, "error");
        else toast(`${doc.original_name} processed successfully.`, "success");
      }
    } catch {
      clearInterval(pollTimers[docId]);
      delete pollTimers[docId];
    }
  }, 2000);
}

docsTbody.addEventListener("click", async e => {
  const btn = e.target.closest("[data-delete]");
  if (!btn) return;
  const id = btn.dataset.delete;
  if (!confirm("Delete this document and all extracted data?")) return;
  try {
    await apiFetch(`/documents/${id}`, { method: "DELETE" });
    docsTbody.querySelector(`tr[data-id="${id}"]`)?.remove();
    if (!docsTbody.querySelector("tr")) docsEmpty.classList.remove("hidden");
    toast("Document deleted.", "success");
  } catch {
    toast("Delete failed.", "error");
  }
});

// ── INVOICES TAB ───────────────────────────────────────────────────────────

let invPage = 1;
const INV_PAGE_SIZE = 20;
let invTotal = 0;

function invFilters() {
  return {
    vendor_name:  document.getElementById("inv-vendor").value.trim(),
    date_from:    document.getElementById("inv-from").value,
    date_to:      document.getElementById("inv-to").value,
    currency:     document.getElementById("inv-currency").value.trim(),
    page:         invPage,
    page_size:    INV_PAGE_SIZE,
  };
}

async function fetchInvoices() {
  const tbody = document.getElementById("inv-tbody");
  const empty = document.getElementById("inv-empty");
  const pgEl  = document.getElementById("inv-pagination");
  skeletonRows(tbody, 6);
  empty.classList.add("hidden");
  pgEl.innerHTML = "";

  try {
    const data = await apiFetch("/invoices" + qs(invFilters()));
    invTotal = data.total;
    tbody.innerHTML = "";

    if (data.items.length === 0) {
      empty.classList.remove("hidden");
      return;
    }

    data.items.forEach(inv => {
      const tr = document.createElement("tr");
      tr.className = "hover:bg-gray-50 cursor-pointer";
      tr.innerHTML = `
        <td class="px-5 py-3 font-medium text-gray-800">${inv.vendor_name ?? "—"}</td>
        <td class="px-5 py-3 text-gray-600">${inv.invoice_number ?? "—"}</td>
        <td class="px-5 py-3 text-gray-500">${fmtDate(inv.invoice_date)}</td>
        <td class="px-5 py-3 text-gray-500">${fmtDate(inv.due_date)}</td>
        <td class="px-5 py-3 text-right font-mono text-gray-800">
          ${inv.currency ?? ""} ${fmtNum(inv.total_amount)}
        </td>
        <td class="px-5 py-3">
          <button class="text-blue-600 hover:underline text-sm" data-view-invoice="${inv.id}">View</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    renderPagination(pgEl, invPage, Math.ceil(invTotal / INV_PAGE_SIZE), p => {
      invPage = p; fetchInvoices();
    });
  } catch (err) {
    toast("Failed to load invoices.", "error");
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
  }
}

document.getElementById("inv-tbody").addEventListener("click", async e => {
  const btn = e.target.closest("[data-view-invoice]");
  if (!btn) return;
  const id = btn.dataset.viewInvoice;
  try {
    const inv = await apiFetch(`/invoices/${id}`);
    openInvoicePanel(inv);
  } catch {
    toast("Failed to load invoice.", "error");
  }
});

let invDebounce;
["inv-vendor", "inv-from", "inv-to", "inv-currency"].forEach(id => {
  document.getElementById(id).addEventListener("input", () => {
    clearTimeout(invDebounce);
    invDebounce = setTimeout(() => { invPage = 1; fetchInvoices(); }, 400);
  });
});
document.getElementById("inv-apply").addEventListener("click", () => { invPage = 1; fetchInvoices(); });
document.getElementById("inv-clear").addEventListener("click", () => {
  ["inv-vendor","inv-from","inv-to","inv-currency"].forEach(id => {
    document.getElementById(id).value = "";
  });
  invPage = 1; fetchInvoices();
});

// ── Invoice detail panel ───────────────────────────────────────────────────

const detailPanel    = document.getElementById("detail-panel");
const detailBackdrop = document.getElementById("detail-backdrop");
const detailBody     = document.getElementById("detail-body");
const detailTitle    = document.getElementById("detail-title");

function openInvoicePanel(inv) {
  detailTitle.textContent = inv.vendor_name ? `Invoice — ${inv.vendor_name}` : "Invoice Detail";
  detailBody.innerHTML = `
    <dl class="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Vendor</dt><dd class="font-medium">${inv.vendor_name ?? "—"}</dd></div>
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Invoice #</dt><dd class="font-medium">${inv.invoice_number ?? "—"}</dd></div>
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Date</dt><dd>${fmtDate(inv.invoice_date)}</dd></div>
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Due Date</dt><dd>${fmtDate(inv.due_date)}</dd></div>
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Total</dt><dd class="font-semibold">${inv.currency ?? ""} ${fmtNum(inv.total_amount)}</dd></div>
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Tax</dt><dd>${inv.currency ?? ""} ${fmtNum(inv.tax_amount)}</dd></div>
      <div><dt class="text-gray-400 text-xs uppercase tracking-wide">Currency</dt><dd>${inv.currency ?? "—"}</dd></div>
    </dl>

    ${inv.line_items.length ? `
    <div>
      <h3 class="text-xs uppercase tracking-wide text-gray-400 mb-2">Line Items</h3>
      <table class="w-full text-sm border border-gray-100 rounded-lg overflow-hidden">
        <thead class="bg-gray-50 text-gray-500 text-xs">
          <tr>
            <th class="text-left px-3 py-2">Description</th>
            <th class="text-right px-3 py-2">Qty</th>
            <th class="text-right px-3 py-2">Unit Price</th>
            <th class="text-right px-3 py-2">Total</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          ${inv.line_items.map(li => `
          <tr>
            <td class="px-3 py-2 text-gray-700">${li.description ?? "—"}</td>
            <td class="px-3 py-2 text-right text-gray-600">${li.quantity != null ? Number(li.quantity) : "—"}</td>
            <td class="px-3 py-2 text-right text-gray-600 font-mono">${fmtNum(li.unit_price)}</td>
            <td class="px-3 py-2 text-right font-mono font-medium">${fmtNum(li.total)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>` : `<p class="text-sm text-gray-400">No line items.</p>`}
  `;

  detailBackdrop.classList.remove("hidden");
  detailPanel.classList.add("open");
  document.addEventListener("keydown", handleDetailEsc);
}

function closeInvoicePanel() {
  detailPanel.classList.remove("open");
  detailBackdrop.classList.add("hidden");
  document.removeEventListener("keydown", handleDetailEsc);
}

function handleDetailEsc(e) {
  if (e.key === "Escape") closeInvoicePanel();
}

document.getElementById("detail-close").addEventListener("click", closeInvoicePanel);
detailBackdrop.addEventListener("click", closeInvoicePanel);

// ── TRANSACTIONS TAB ───────────────────────────────────────────────────────

let txnPage = 1;
const TXN_PAGE_SIZE = 20;
let txnTotal = 0;

function txnFilters() {
  return {
    q:         document.getElementById("txn-desc").value.trim(),
    date_from: document.getElementById("txn-from").value,
    date_to:   document.getElementById("txn-to").value,
    currency:  document.getElementById("txn-currency").value.trim(),
    page:      txnPage,
    page_size: TXN_PAGE_SIZE,
  };
}

async function fetchTransactions() {
  const tbody = document.getElementById("txn-tbody");
  const empty = document.getElementById("txn-empty");
  const pgEl  = document.getElementById("txn-pagination");
  skeletonRows(tbody, 5);
  empty.classList.add("hidden");
  pgEl.innerHTML = "";

  try {
    const data = await apiFetch("/transactions" + qs(txnFilters()));
    txnTotal = data.total;
    tbody.innerHTML = "";

    if (data.items.length === 0) {
      empty.classList.remove("hidden");
      return;
    }

    data.items.forEach(txn => {
      const isDebit  = txn.debit_credit?.toLowerCase() === "debit";
      const isCredit = txn.debit_credit?.toLowerCase() === "credit";
      const amountClass = isDebit ? "text-red-600" : isCredit ? "text-green-600" : "text-gray-800";
      const tr = document.createElement("tr");
      tr.className = "hover:bg-gray-50";
      tr.innerHTML = `
        <td class="px-5 py-3 text-gray-500">${fmtDate(txn.transaction_date)}</td>
        <td class="px-5 py-3 text-gray-800 max-w-xs truncate" title="${txn.description ?? ""}">${txn.description ?? "—"}</td>
        <td class="px-5 py-3 text-right font-mono font-medium ${amountClass}">${fmtNum(txn.amount)}</td>
        <td class="px-5 py-3 text-gray-500">${txn.currency ?? "—"}</td>
        <td class="px-5 py-3 ${amountClass} font-medium">${txn.debit_credit ?? "—"}</td>
      `;
      tbody.appendChild(tr);
    });

    renderPagination(pgEl, txnPage, Math.ceil(txnTotal / TXN_PAGE_SIZE), p => {
      txnPage = p; fetchTransactions();
    });
  } catch {
    toast("Failed to load transactions.", "error");
    tbody.innerHTML = "";
    empty.classList.remove("hidden");
  }
}

let txnDebounce;
["txn-desc", "txn-from", "txn-to", "txn-currency"].forEach(id => {
  document.getElementById(id).addEventListener("input", () => {
    clearTimeout(txnDebounce);
    txnDebounce = setTimeout(() => { txnPage = 1; fetchTransactions(); }, 400);
  });
});
document.getElementById("txn-apply").addEventListener("click", () => { txnPage = 1; fetchTransactions(); });
document.getElementById("txn-clear").addEventListener("click", () => {
  ["txn-desc","txn-from","txn-to","txn-currency"].forEach(id => {
    document.getElementById(id).value = "";
  });
  txnPage = 1; fetchTransactions();
});

// ── Pagination ─────────────────────────────────────────────────────────────

function renderPagination(container, currentPage, totalPages, onNavigate) {
  if (totalPages <= 1) return;
  container.innerHTML = `
    <button class="px-3 py-1 border border-gray-200 rounded text-sm hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            ${currentPage <= 1 ? "disabled" : ""} id="pg-prev">← Prev</button>
    <span class="text-gray-600">Page ${currentPage} of ${totalPages}</span>
    <button class="px-3 py-1 border border-gray-200 rounded text-sm hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            ${currentPage >= totalPages ? "disabled" : ""} id="pg-next">Next →</button>
  `;
  container.querySelector("#pg-prev")?.addEventListener("click", () => onNavigate(currentPage - 1));
  container.querySelector("#pg-next")?.addEventListener("click", () => onNavigate(currentPage + 1));
}

// ── Boot ───────────────────────────────────────────────────────────────────

activateTab("upload");

import csv
import io

from app.parsers.base import ParseError, TransactionParseResult
from app.parsers.normalizers import normalize_currency, parse_amount, parse_date

REQUIRED_COLUMNS = {"date", "description", "amount"}
COLUMN_ALIASES: dict[str, list[str]] = {
    "date": ["date", "transaction_date", "trans_date", "value_date", "posted_date"],
    "description": ["description", "details", "narration", "memo", "particulars"],
    "amount": ["amount", "debit", "credit", "transaction_amount"],
    "currency": ["currency", "ccy"],
    "balance": ["balance", "running_balance", "closing_balance"],
    "reference": ["reference", "ref", "transaction_id", "txn_id"],
    "debit_credit": ["debit_credit", "dr_cr", "type", "transaction_type"],
}


def _map_columns(headers: list[str]) -> dict[str, str]:
    lower_headers = [h.strip().lower() for h in headers]
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_headers:
                mapping[canonical] = headers[lower_headers.index(alias)]
                break
    return mapping


class CsvStatementParser:
    def parse(self, data: bytes) -> list[TransactionParseResult]:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            return []
        mapping = _map_columns(list(reader.fieldnames))
        missing = REQUIRED_COLUMNS - set(mapping.keys())
        if missing:
            raise ParseError(f"CSV missing required columns: {missing}")

        results = []
        for row in reader:
            if not any(row.values()):
                continue
            warnings: list[str] = []
            txn = TransactionParseResult(parse_warnings=warnings)

            raw_date = row.get(mapping["date"], "")
            txn.transaction_date = parse_date(raw_date)
            if txn.transaction_date is None and raw_date:
                warnings.append(f"unparseable date: {raw_date!r}")

            txn.description = row.get(mapping.get("description", ""), "").strip() or None

            raw_amount = row.get(mapping["amount"], "")
            txn.amount = parse_amount(raw_amount)
            if txn.amount is None and raw_amount:
                warnings.append(f"unparseable amount: {raw_amount!r}")

            if "currency" in mapping:
                txn.currency = normalize_currency(row.get(mapping["currency"], ""))
            if "balance" in mapping:
                txn.balance = parse_amount(row.get(mapping["balance"], ""))
            if "reference" in mapping:
                txn.reference = row.get(mapping["reference"], "").strip() or None
            if "debit_credit" in mapping:
                raw_dc = row.get(mapping["debit_credit"], "").strip().lower()
                if raw_dc in ("debit", "dr", "d"):
                    txn.debit_credit = "debit"
                elif raw_dc in ("credit", "cr", "c"):
                    txn.debit_credit = "credit"

            results.append(txn)
        return results

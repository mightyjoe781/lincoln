from app.parsers.base import ParseError
from app.parsers.csv_statement import CsvStatementParser
from app.parsers.pdf_invoice import PdfInvoiceParser

_REGISTRY: dict[str, type] = {
    "application/pdf": PdfInvoiceParser,
    "text/csv": CsvStatementParser,
    "text/plain": CsvStatementParser,
}

_TYPE_MAP: dict[str, str] = {
    "application/pdf": "pdf_invoice",
    "text/csv": "csv_statement",
    "text/plain": "csv_statement",
}


def get_parser(mime_type: str):
    cls = _REGISTRY.get(mime_type)
    if cls is None:
        raise ParseError(f"No parser for mime type: {mime_type!r}")
    return cls()


def get_file_type(mime_type: str) -> str:
    return _TYPE_MAP.get(mime_type, "unknown")

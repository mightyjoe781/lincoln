import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document
from app.db.models.invoice import Invoice
from app.db.models.line_item import LineItem
from app.db.models.transaction import Transaction
from app.parsers.registry import get_file_type
from app.storage.local import LocalFileStorage
from app.worker.tasks import parse_document_task


class DocumentService:
    def __init__(self, db: AsyncSession, storage: LocalFileStorage):
        self.db = db
        self.storage = storage

    async def upload(
        self, file_bytes: bytes, filename: str, mime_type: str = "application/pdf"
    ) -> Document:
        checksum = hashlib.sha256(file_bytes).hexdigest()

        existing = await self.db.scalar(select(Document).where(Document.checksum == checksum))
        if existing:
            return existing

        file_type = get_file_type(mime_type)
        file_path = await self.storage.save(file_bytes, filename, checksum)
        ext = filename[filename.rfind(".") :] if "." in filename else ""

        doc = Document(
            filename=f"{checksum}{ext}",
            original_name=filename,
            file_type=file_type,
            mime_type=mime_type,
            file_size=len(file_bytes),
            file_path=file_path,
            checksum=checksum,
            status="pending",
        )
        self.db.add(doc)
        await self.db.commit()
        await self.db.refresh(doc)

        parse_document_task.delay(str(doc.id))
        return doc

    async def _persist_parsed_data(self, doc: Document, result, file_type: str) -> None:
        if file_type == "pdf_invoice":
            invoice = Invoice(
                document_id=doc.id,
                vendor_name=result.vendor_name,
                invoice_date=result.invoice_date,
                due_date=result.due_date,
                invoice_number=result.invoice_number,
                total_amount=result.total_amount,
                currency=result.currency,
                tax_amount=result.tax_amount,
                raw_text=result.raw_text,
            )
            self.db.add(invoice)
            await self.db.flush()
            for li in result.line_items:
                self.db.add(
                    LineItem(
                        invoice_id=invoice.id,
                        description=li.description,
                        quantity=li.quantity,
                        unit_price=li.unit_price,
                        total=li.total,
                        currency=li.currency,
                    )
                )
        elif file_type == "csv_statement":
            for txn in result:
                self.db.add(
                    Transaction(
                        document_id=doc.id,
                        transaction_date=txn.transaction_date,
                        description=txn.description,
                        amount=txn.amount,
                        currency=txn.currency,
                        debit_credit=txn.debit_credit,
                        balance=txn.balance,
                        reference=txn.reference,
                    )
                )

    async def get(self, doc_id: uuid.UUID) -> Document | None:
        return await self.db.get(Document, doc_id)

    async def list(self, page: int = 1, page_size: int = 20) -> list[Document]:
        offset = (page - 1) * page_size
        result = await self.db.scalars(select(Document).offset(offset).limit(page_size))
        return list(result)

    async def delete(self, doc_id: uuid.UUID) -> bool:
        doc = await self.db.get(Document, doc_id)
        if not doc:
            return False
        await self.storage.delete(doc.file_path)
        await self.db.delete(doc)
        await self.db.commit()
        return True

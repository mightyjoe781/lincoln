import asyncio
from celery import shared_task
from app.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def parse_document_task(self, document_id: str):
    """Parse a document and persist results. Runs in Celery worker."""
    asyncio.run(_parse_document(document_id))


async def _parse_document(document_id: str):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from app.core.config import settings
    from app.db.models.document import Document
    from app.parsers.registry import get_parser, get_file_type
    from app.storage.local import LocalFileStorage
    from datetime import datetime, timezone

    engine = create_async_engine(settings.database_url)
    AsyncSession = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncSession() as db:
        doc = await db.get(Document, document_id)
        if not doc:
            return

        try:
            doc.status = "processing"
            await db.commit()

            storage = LocalFileStorage(settings.upload_dir)
            file_bytes = await storage.read(doc.file_path)

            parser = get_parser(doc.mime_type)
            file_type = get_file_type(doc.mime_type)

            await _persist_parsed(db, doc, parser, file_bytes, file_type)

            doc.status = "done"
            doc.processed_at = datetime.now(timezone.utc)
        except Exception as exc:
            doc.status = "failed"
            doc.error_message = str(exc)

        await db.commit()
    await engine.dispose()


async def _persist_parsed(db, doc, parser, file_bytes, file_type):
    from app.db.models.invoice import Invoice
    from app.db.models.line_item import LineItem
    from app.db.models.transaction import Transaction
    import uuid

    if file_type == "pdf_invoice":
        result = parser.parse(file_bytes)
        invoice = Invoice(
            id=uuid.uuid4(),
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
        db.add(invoice)
        await db.flush()
        for li in result.line_items:
            db.add(LineItem(
                id=uuid.uuid4(),
                invoice_id=invoice.id,
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                total=li.total,
                currency=li.currency,
            ))
    else:
        results = parser.parse(file_bytes)
        for r in results:
            db.add(Transaction(
                id=uuid.uuid4(),
                document_id=doc.id,
                transaction_date=r.transaction_date,
                description=r.description,
                amount=r.amount,
                currency=r.currency,
                debit_credit=r.debit_credit,
                balance=r.balance,
                reference=r.reference,
            ))

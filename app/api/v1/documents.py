import hashlib
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models.user import User
from app.core.config import settings
from app.db.models.document import Document
from app.schemas.document import (
    DocumentBatchUploadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResult,
)
from app.services.document_service import DocumentService
from app.core.limiter import limiter
from app.storage.local import LocalFileStorage

router = APIRouter(prefix="/documents", tags=["documents"])


def get_storage() -> LocalFileStorage:
    return LocalFileStorage(settings.upload_dir)


@router.post(
    "/upload",
    response_model=DocumentBatchUploadResponse,
    status_code=status.HTTP_200_OK,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "One or more PDF invoices or CSV bank statements",
                            }
                        },
                    }
                }
            },
            "required": True,
        }
    },
)
@limiter.limit("30/minute")
async def upload_document(
    request: Request,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = DocumentService(db, get_storage())
    results: list[DocumentUploadResult] = []

    for file in files:
        if file.content_type not in settings.allowed_mime_types:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{file.filename}: unsupported type '{file.content_type}'. Allowed: {settings.allowed_mime_types}",
            )

        file_bytes = await file.read()

        if len(file_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{file.filename}: file too large ({len(file_bytes)} bytes). Max: {settings.max_upload_size_bytes}",
            )

        checksum = hashlib.sha256(file_bytes).hexdigest()
        existing = await db.scalar(select(Document).where(Document.checksum == checksum))

        if existing:
            results.append(DocumentUploadResult(
                document=DocumentResponse.model_validate(existing),
                created=False,
            ))
            continue

        mime = file.content_type or "application/octet-stream"
        doc = await svc.upload(file_bytes, file.filename or "upload", mime)
        results.append(DocumentUploadResult(
            document=DocumentResponse.model_validate(doc),
            created=True,
        ))

    created = sum(1 for r in results if r.created)
    return DocumentBatchUploadResponse(
        results=results,
        total=len(results),
        created=created,
        duplicates=len(results) - created,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(select(func.count()).select_from(Document))
    svc = DocumentService(db, get_storage())
    docs = await svc.list(page=page, page_size=page_size)
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(d) for d in docs],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    svc = DocumentService(db, get_storage())
    doc = await svc.get(doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    svc = DocumentService(db, get_storage())
    deleted = await svc.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    original_name: str
    file_type: str
    mime_type: str
    file_size: int
    checksum: str
    status: str
    error_message: Optional[str] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class DocumentUploadResult(BaseModel):
    document: DocumentResponse
    created: bool  # True = new upload, False = duplicate


class DocumentBatchUploadResponse(BaseModel):
    results: list[DocumentUploadResult]
    total: int
    created: int
    duplicates: int

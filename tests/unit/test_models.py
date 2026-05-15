from app.db.models.document import Document


def test_document_model_defaults():
    doc = Document(
        filename="x.pdf",
        original_name="x.pdf",
        file_type="pdf_invoice",
        mime_type="application/pdf",
        file_size=1024,
        file_path="/tmp/x.pdf",
        checksum="abc123",
    )
    assert doc.status == "pending"
    assert doc.id is None

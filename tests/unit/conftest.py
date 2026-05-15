from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_celery_task():
    """Prevent Celery tasks from trying to connect to Redis during unit tests."""
    mock_task = MagicMock()
    with patch("app.services.document_service.parse_document_task", mock_task):
        yield mock_task

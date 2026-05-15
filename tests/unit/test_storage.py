from pathlib import Path
from unittest.mock import patch

import pytest

from app.storage.local import LocalFileStorage


@pytest.mark.asyncio
async def test_save_returns_deterministic_path(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    path = await storage.save(b"data", "invoice.pdf", "abc123")
    assert path.endswith("abc123.pdf")


@pytest.mark.asyncio
async def test_save_twice_same_checksum_does_not_duplicate(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    p1 = await storage.save(b"data", "a.pdf", "same")
    p2 = await storage.save(b"data", "b.pdf", "same")
    assert p1 == p2


@pytest.mark.asyncio
async def test_delete_removes_file(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    path = await storage.save(b"content", "test.pdf", "del123")
    assert await storage.exists(path)
    await storage.delete(path)
    assert not await storage.exists(path)


@pytest.mark.asyncio
async def test_read_returns_correct_bytes(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    path = await storage.save(b"hello world", "test.txt", "hw123")
    content = await storage.read(path)
    assert content == b"hello world"


@pytest.mark.asyncio
async def test_exists_returns_false_for_missing_file(tmp_path):
    storage = LocalFileStorage(base_dir=tmp_path)
    assert not await storage.exists(str(tmp_path / "ghost.pdf"))


@pytest.mark.asyncio
async def test_delete_nonexistent_file_does_not_raise(tmp_path):
    """Deleting a path that never existed should be a no-op."""
    storage = LocalFileStorage(base_dir=tmp_path)
    await storage.delete(str(tmp_path / "nonexistent.pdf"))  # must not raise


@pytest.mark.asyncio
async def test_save_permission_error_propagates(tmp_path):
    """If the filesystem refuses the write, the OSError should bubble up."""
    storage = LocalFileStorage(base_dir=tmp_path)
    with patch.object(Path, "write_bytes", side_effect=PermissionError("read-only filesystem")):
        with pytest.raises(PermissionError):
            await storage.save(b"data", "invoice.pdf", "abc123")


@pytest.mark.asyncio
async def test_base_dir_created_if_missing(tmp_path):
    """Constructor must create missing parent directories."""
    new_dir = tmp_path / "deep" / "nested" / "dir"
    assert not new_dir.exists()
    LocalFileStorage(base_dir=new_dir)
    assert new_dir.exists()

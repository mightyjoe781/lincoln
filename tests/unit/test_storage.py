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

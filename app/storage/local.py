from pathlib import Path

import aiofiles


class LocalFileStorage:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, data: bytes, original_filename: str, checksum: str) -> str:
        ext = Path(original_filename).suffix
        dest = self.base_dir / f"{checksum}{ext}"
        if not dest.exists():
            dest.write_bytes(data)
        return str(dest)

    async def delete(self, file_path: str) -> None:
        p = Path(file_path)
        if p.exists():
            p.unlink()

    async def exists(self, file_path: str) -> bool:
        return Path(file_path).exists()

    async def read(self, file_path: str) -> bytes:
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

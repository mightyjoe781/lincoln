"""
Seed script — creates the default admin user on container startup.

Run automatically by the Dockerfile CMD between alembic and uvicorn.
Only acts when ADMIN_EMAIL and ADMIN_PASSWORD are set; safe to run on
every restart (idempotent — skips creation if the user already exists).
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.user import User  # noqa: F401 — ensures table is known


async def seed() -> None:
    if not settings.admin_email or not settings.admin_password:
        print("ADMIN_EMAIL / ADMIN_PASSWORD not set — skipping default user creation.")
        return

    engine = create_async_engine(settings.database_url)
    AsyncSession = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncSession() as db:
        existing = await db.scalar(select(User).where(User.email == settings.admin_email))
        if existing:
            print(f"Admin user already exists: {settings.admin_email}")
        else:
            db.add(
                User(
                    email=settings.admin_email,
                    hashed_password=hash_password(settings.admin_password),
                )
            )
            await db.commit()
            print(f"Created admin user: {settings.admin_email}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

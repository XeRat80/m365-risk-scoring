from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings


def async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
admin_engine = create_async_engine(async_url(settings.database_admin_url), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
AdminSessionLocal = async_sessionmaker(admin_engine, expire_on_commit=False)


async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session, session.begin():
        await session.execute(text("select set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
        yield session


async def admin_session() -> AsyncIterator[AsyncSession]:
    async with AdminSessionLocal() as session:
        yield session

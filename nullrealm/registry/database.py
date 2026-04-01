"""Async database engine, session factory, and init helpers."""

import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://nullrealm:nullrealm_dev@localhost:5432/nullrealm",
)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI dependency — yields an async session then closes it."""
    async with async_session() as session:
        yield session


async def init_db():
    """Create pgvector extension and all tables."""
    from nullrealm.registry.models import Base  # noqa: F811

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

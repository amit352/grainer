"""Async SQLAlchemy session factory and initialiser."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database.models import Base

_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)

_SessionFactory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables if they don't exist and apply lightweight column migrations."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add columns introduced after initial release (safe no-ops if already present)
        for stmt in [
            "ALTER TABLE scans ADD COLUMN vendor_id INTEGER REFERENCES vendors(id)",
            "ALTER TABLE scans ADD COLUMN lot_id VARCHAR(255)",
        ]:
            try:
                await conn.exec_driver_sql(stmt)
            except Exception:
                pass  # column already exists


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a transactional async session."""
    async with _SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

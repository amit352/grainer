"""Shared FastAPI dependencies."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session

DBSession = Depends(db_session)

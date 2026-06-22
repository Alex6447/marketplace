"""Async-движок и фабрика сессий SQLAlchemy для приложения (api/worker).

Движок ленивый и кэшируется на процесс. Драйвер — psycopg (v3) в async-режиме;
строка подключения берётся из :mod:`marketplace_shared.db.config`. Alembic
использует собственный sync-движок (см. `migrations/env.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from marketplace_shared.db.config import get_db_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Singleton async-движок (psycopg v3). `pool_pre_ping` — отсев мёртвых коннектов."""
    settings = get_db_settings()
    return create_async_engine(settings.as_async_url(), pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Singleton-фабрика async-сессий. `expire_on_commit=False` — объекты живут после commit."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: одна сессия на запрос, с авто-закрытием."""
    async with get_sessionmaker()() as session:
        yield session

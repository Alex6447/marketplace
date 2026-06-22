"""Модель данных и доступ к БД (docs/plan.md, раздел 5).

Экспортирует декларативную базу, ORM-модели и фабрику сессий. Alembic-миграции
живут в корне репозитория (`migrations/`) и опираются на :data:`Base.metadata`.
"""

from marketplace_shared.db.base import Base
from marketplace_shared.db.config import DbSettings, get_db_settings
from marketplace_shared.db.models import (
    Card,
    CardSet,
    CardVersion,
    Feedback,
    Job,
    Product,
    ProductAsset,
    Project,
)
from marketplace_shared.db.session import get_engine, get_session, get_sessionmaker

__all__ = [
    "Base",
    "DbSettings",
    "get_db_settings",
    "Project",
    "Product",
    "ProductAsset",
    "CardSet",
    "Card",
    "CardVersion",
    "Feedback",
    "Job",
    "get_engine",
    "get_sessionmaker",
    "get_session",
]

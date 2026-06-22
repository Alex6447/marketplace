"""Базовый класс ORM и общие примитивы модели данных.

Все таблицы наследуются от :class:`Base`. Единое соглашение об именах ограничений
(`naming_convention`) фиксирует имена индексов/FK/PK, чтобы автогенерация Alembic
давала стабильные, воспроизводимые миграции (а не случайные имена от СУБД).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Стабильные имена ограничений — основа для надёжного `alembic revision --autogenerate`.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Декларативная база для всех ORM-моделей проекта."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID-первичный ключ, генерируемый на стороне приложения."""
    return mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Метка создания записи. `server_default` — время проставляет СУБД."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )

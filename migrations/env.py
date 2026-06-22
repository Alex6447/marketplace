"""Окружение Alembic для миграций.

Строка подключения и метаданные берутся из общего пакета
:mod:`marketplace_shared.db` — один источник правды с приложением. Alembic
работает синхронным движком psycopg (v3); приложение — асинхронным (тот же драйвер).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Импорт моделей регистрирует таблицы в Base.metadata (нужно для autogenerate).
import marketplace_shared.db.models  # noqa: F401
from marketplace_shared.db import Base
from marketplace_shared.db.config import get_db_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Sync-строка (postgresql+psycopg) из DATABASE_URL — переопределяет sqlalchemy.url.
config.set_main_option("sqlalchemy.url", get_db_settings().as_psycopg_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Миграции без подключения — генерация SQL по URL ('offline' режим)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Миграции с живым подключением к БД ('online' режим)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

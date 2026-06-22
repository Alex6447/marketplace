"""Конфигурация подключения к БД через pydantic-settings.

Читается из переменных окружения (и `.env` при локальном запуске). Ключ
`DATABASE_URL` совпадает с `.env_example` и docker-compose. Строка хранится в
нейтральном виде `postgresql://…`; драйвер подставляется в коде (см.
:func:`as_psycopg_url` / :func:`as_async_url`), чтобы `.env` не зависел от драйвера.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Диалект SQLAlchemy для psycopg (v3). Один драйвер на sync (Alembic) и async (app).
_PSYCOPG_DIALECT = "postgresql+psycopg"


def _with_driver(url: str) -> str:
    """Подставить psycopg-диалект в нейтральную строку `postgresql://…`.

    Если драйвер уже указан явно (`postgresql+something://`), строка не трогается.
    """
    if url.startswith(f"{_PSYCOPG_DIALECT}://"):
        return url
    if url.startswith("postgresql+"):  # явно задан другой драйвер — уважаем выбор
        return url
    if url.startswith("postgresql://"):
        return _PSYCOPG_DIALECT + url[len("postgresql") :]
    if url.startswith("postgres://"):  # legacy-схема (напр. от облачных провайдеров)
        return _PSYCOPG_DIALECT + url[len("postgres") :]
    return url


class DbSettings(BaseSettings):
    """Настройки доступа к БД. Дефолт — локальная dev-БД `marketplace`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://postgres:postgres@localhost:5432/marketplace"

    def as_psycopg_url(self) -> str:
        """Sync-строка для Alembic и однократных операций (psycopg v3)."""
        return _with_driver(self.database_url)

    def as_async_url(self) -> str:
        """Async-строка для движка приложения (psycopg v3 поддерживает asyncio)."""
        return _with_driver(self.database_url)


@lru_cache
def get_db_settings() -> DbSettings:
    """Singleton-доступ к настройкам БД (кэш на время жизни процесса)."""
    return DbSettings()

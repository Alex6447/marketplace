"""Конфигурация хранилища файлов (MinIO / S3) через pydantic-settings.

Читается из переменных окружения (и `.env` при локальном запуске). Ключи
совпадают с `.env_example` и docker-compose (`S3_ENDPOINT`, `S3_ACCESS_KEY`,
`S3_SECRET_KEY`, `S3_BUCKET`). Дефолты рассчитаны на локальный MinIO из
docker-compose (запуск кода с хост-машины).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    """Настройки доступа к S3-совместимому хранилищу."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Адрес S3 API. Локально — MinIO на :9000; в проде — endpoint S3-совместимого хранилища.
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "marketplace"
    #: Регион нужен подписи AWS SigV4. Для MinIO значение произвольно, но обязано быть задано.
    s3_region: str = "us-east-1"


@lru_cache
def get_storage_settings() -> StorageSettings:
    """Singleton-доступ к настройкам хранилища (кэш на время жизни процесса)."""
    return StorageSettings()

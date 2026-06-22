"""Конфигурация тонкого API через pydantic-settings.

Значения читаются из переменных окружения (и `.env` при локальном запуске).
Имена ключей совпадают с `.env_example` и docker-compose, чтобы один и тот же
конфиг работал и с хост-машины, и внутри docker-сети.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения.

    Поля с дефолтами рассчитаны на запуск с хост-машины (localhost). В docker-сети
    соответствующие переменные переопределяются именами сервисов (postgres/redis).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Подключения к инфраструктуре ---
    database_url: str = "postgresql://postgres:postgres@localhost:5432/marketplace"
    redis_url: str = "redis://localhost:6379/0"

    # --- CORS: источники фронтенда, которым разрешены запросы к API ---
    # Vite dev-сервер по умолчанию слушает 5173 (и на 127.0.0.1, и на localhost).
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


@lru_cache
def get_settings() -> Settings:
    """Singleton-доступ к настройкам (кэшируется на время жизни процесса)."""
    return Settings()

"""Конфигурация провайдер-слоя через pydantic-settings.

Читается из переменных окружения (и `.env` при локальном запуске). Имена ключей
совпадают с `.env_example`. Режим развёртывания и выбор конкретных провайдеров
задаётся здесь — пайплайн их не знает (docs/plan.md, 4.1).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DeploymentMode = Literal["hosted", "local", "hybrid"]


class ProviderSettings(BaseSettings):
    """Настройки выбора провайдеров и доступа к ним.

    Дефолты рассчитаны на офлайн-старт: оба провайдера — `echo`, ключи не нужны.
    Это позволяет гонять пайплайн и тесты без сети и без расходов на API.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Справочный режим (hosted/local/hybrid). На выбор реализаций влияют поля ниже.
    deployment_mode: DeploymentMode = "hosted"

    # --- LLM ---
    llm_provider: str = "echo"
    llm_model: str | None = None  # None → дефолтная модель выбранного провайдера
    anthropic_api_key: str | None = None

    # --- Image ---
    image_provider: str = "echo"
    image_model: str | None = None
    gemini_api_key: str | None = None
    bfl_api_key: str | None = None  # Black Forest Labs — Flux.1 Kontext


@lru_cache
def get_provider_settings() -> ProviderSettings:
    """Singleton-доступ к настройкам провайдеров (кэш на время жизни процесса)."""
    return ProviderSettings()

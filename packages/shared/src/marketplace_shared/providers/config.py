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
    #: Локальный Ollama (llm_provider='ollama', Этап 6). Сервер должен быть запущен.
    #: NB: на Windows порт 11434 может попасть в зарезервированный диапазон — тогда
    #: поднимать Ollama на другом порту (напр. 11500) и указать его здесь.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"

    # --- Image ---
    image_provider: str = "echo"
    image_model: str | None = None
    gemini_api_key: str | None = None
    bfl_api_key: str | None = None  # Black Forest Labs — Flux.1 Kontext

    # --- Локальный ComfyUI (image_provider='comfyui', Этап 6) ---
    #: Адрес запущенного сервера ComfyUI и имена моделей в его папках models/*.
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_unet: str = "flux1-kontext-dev-Q4_K_M.gguf"
    comfyui_t5: str = "t5-v1_1-xxl-encoder-Q5_K_M.gguf"
    comfyui_clip_l: str = "clip_l.safetensors"
    comfyui_vae: str = "ae.safetensors"
    comfyui_steps: int = 20
    comfyui_guidance: float = 2.5
    #: Имя модели BiRefNet для matting='birefnet' (нода ComfyUI_BiRefNet_ll авто-скачает).
    comfyui_birefnet_model: str = "General"

    # --- Matting (стадия [4] — удаление фона/маска) ---
    #: 'simple' — офлайн-кеинг по цвету фона (Pillow, без GPU). 'birefnet' — SOTA-вырез
    #: через локальный ComfyUI (Этап 6, нужен запущенный сервер). 'sam2' — позже.
    matting_provider: str = "simple"
    matting_model: str | None = None


@lru_cache
def get_provider_settings() -> ProviderSettings:
    """Singleton-доступ к настройкам провайдеров (кэш на время жизни процесса)."""
    return ProviderSettings()

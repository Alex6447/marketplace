"""Конфигурация движка наложения текста (стадия [6]) через pydantic-settings.

Выбор backend'а — ключ ``TEXT_RENDERER``. Дефолт ``pillow`` рассчитан на офлайн-старт
(без браузера); основной режим ``playwright`` включается, когда поставлен extra
``render`` тяжёлого воркера (docs/plan.md, 4.1 и раздел 7, Этап 3).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class TextRenderSettings(BaseSettings):
    """Настройки движка наложения текста."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: 'pillow' — офлайн-fallback (без браузера); 'playwright' — HTML/CSS через Chromium.
    text_renderer: str = "pillow"
    #: Путь к TTF-шрифту для Pillow-бэкенда (с кириллицей). None → автоподбор системного.
    text_render_font: str | None = None


@lru_cache
def get_text_render_settings() -> TextRenderSettings:
    """Singleton-доступ к настройкам движка текста (кэш на время жизни процесса)."""
    return TextRenderSettings()

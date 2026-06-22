"""Фабрики провайдеров: выбор реализации по конфигурации.

`get_llm_provider` / `get_image_provider` — единственная точка, где имя из конфига
(`LLM_PROVIDER`/`IMAGE_PROVIDER`) превращается в конкретную реализацию. Пайплайн
зовёт только их и работает с интерфейсами `LLMProvider`/`ImageProvider`.

Регистрация — явный словарь builder-функций (без импортных side effects): добавление
нового провайдера = одна строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

from .base import ImageProvider, LLMProvider
from .config import ProviderSettings, get_provider_settings
from .echo import EchoImageProvider, EchoLLMProvider
from .errors import ProviderNotConfigured
from .hosted import AnthropicLLMProvider, GeminiImageProvider

LLMBuilder = Callable[[ProviderSettings], LLMProvider]
ImageBuilder = Callable[[ProviderSettings], ImageProvider]


_LLM_BUILDERS: dict[str, LLMBuilder] = {
    "echo": lambda s: EchoLLMProvider(model=s.llm_model),
    "anthropic": lambda s: AnthropicLLMProvider(api_key=s.anthropic_api_key, model=s.llm_model),
}

_IMAGE_BUILDERS: dict[str, ImageBuilder] = {
    "echo": lambda s: EchoImageProvider(model=s.image_model),
    "gemini": lambda s: GeminiImageProvider(api_key=s.gemini_api_key, model=s.image_model),
}


def available_llm_providers() -> list[str]:
    """Имена зарегистрированных LLM-провайдеров."""
    return sorted(_LLM_BUILDERS)


def available_image_providers() -> list[str]:
    """Имена зарегистрированных image-провайдеров."""
    return sorted(_IMAGE_BUILDERS)


def get_llm_provider(settings: ProviderSettings | None = None) -> LLMProvider:
    """Создать LLM-провайдера согласно конфигурации (`LLM_PROVIDER`)."""
    settings = settings or get_provider_settings()
    try:
        builder = _LLM_BUILDERS[settings.llm_provider]
    except KeyError:
        raise ProviderNotConfigured(
            f"Неизвестный LLM_PROVIDER={settings.llm_provider!r}; "
            f"доступны: {available_llm_providers()}"
        ) from None
    return builder(settings)


def get_image_provider(settings: ProviderSettings | None = None) -> ImageProvider:
    """Создать image-провайдера согласно конфигурации (`IMAGE_PROVIDER`)."""
    settings = settings or get_provider_settings()
    try:
        builder = _IMAGE_BUILDERS[settings.image_provider]
    except KeyError:
        raise ProviderNotConfigured(
            f"Неизвестный IMAGE_PROVIDER={settings.image_provider!r}; "
            f"доступны: {available_image_providers()}"
        ) from None
    return builder(settings)

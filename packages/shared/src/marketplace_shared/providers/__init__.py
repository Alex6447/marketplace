"""Провайдер-абстракции: единый интерфейс к LLM и image-моделям.

Публичный API пакета. Пайплайн импортирует контракты, интерфейсы и фабрики отсюда:

    from marketplace_shared.providers import (
        LLMRequest, LLMMessage, get_llm_provider,
        ImageEditRequest, ImageRef, get_image_provider,
    )

См. docs/plan.md, раздел 4.1 (режимы hosted/local/hybrid) и раздел 7, Этап 0.
"""

from __future__ import annotations

from .base import ImageProvider, LLMProvider
from .config import ProviderSettings, get_provider_settings
from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageRef,
    ImageResult,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    Usage,
)
from .echo import EchoImageProvider, EchoLLMProvider
from .errors import ProviderError, ProviderNotConfigured, ProviderNotImplemented
from .hosted import AnthropicLLMProvider, GeminiImageProvider
from .registry import (
    available_image_providers,
    available_llm_providers,
    get_image_provider,
    get_llm_provider,
)

__all__ = [
    # интерфейсы
    "LLMProvider",
    "ImageProvider",
    # контракты
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "ImageRef",
    "ImageEditRequest",
    "ImageGenRequest",
    "ImageResult",
    "Usage",
    # конфигурация
    "ProviderSettings",
    "get_provider_settings",
    # фабрики/реестр
    "get_llm_provider",
    "get_image_provider",
    "available_llm_providers",
    "available_image_providers",
    # реализации
    "EchoLLMProvider",
    "EchoImageProvider",
    "AnthropicLLMProvider",
    "GeminiImageProvider",
    # ошибки
    "ProviderError",
    "ProviderNotConfigured",
    "ProviderNotImplemented",
]

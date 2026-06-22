"""Каркасы hosted-провайдеров (внешние API).

Здесь зафиксирован контракт hosted-реализаций: конструкторы читают модель и ключ
доступа и валидируют конфигурацию. Реальные сетевые вызовы намеренно НЕ реализованы
в этом пункте — они наполняются в следующих пунктах Этапа 0:
- `AnthropicLLMProvider.complete` — пункт «Подключение Claude API»;
- `GeminiImageProvider.edit/generate` — пункт «Подключение editing-API».

До тех пор методы поднимают `ProviderNotImplemented`, а конструктор —
`ProviderNotConfigured` при отсутствии ключа. Это разделяет «интерфейс готов» и
«интеграция подключена», не размывая границы задач плана.
"""

from __future__ import annotations

from .base import ImageProvider, LLMProvider
from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageResult,
    LLMRequest,
    LLMResponse,
)
from .errors import ProviderNotConfigured, ProviderNotImplemented

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"


class AnthropicLLMProvider(LLMProvider):
    """LLM через Claude API (hosted). Интеграция — пункт «Подключение Claude API»."""

    name = "anthropic"

    def __init__(self, *, api_key: str | None, model: str | None = None) -> None:
        if not api_key:
            raise ProviderNotConfigured("Для провайдера 'anthropic' не задан ANTHROPIC_API_KEY")
        self._api_key = api_key
        self._model = model or DEFAULT_ANTHROPIC_MODEL

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise ProviderNotImplemented(
            "AnthropicLLMProvider.complete реализуется в пункте «Подключение Claude API» "
            "(docs/plan.md, Этап 0)"
        )


class GeminiImageProvider(ImageProvider):
    """Editing-модель через Gemini API (hosted). Интеграция — пункт «editing-API»."""

    name = "gemini"

    def __init__(self, *, api_key: str | None, model: str | None = None) -> None:
        if not api_key:
            raise ProviderNotConfigured("Для провайдера 'gemini' не задан GEMINI_API_KEY")
        self._api_key = api_key
        self._model = model or DEFAULT_GEMINI_IMAGE_MODEL

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        raise ProviderNotImplemented(
            "GeminiImageProvider.edit реализуется в пункте «Подключение editing-API» "
            "(docs/plan.md, Этап 0)"
        )

    async def generate(self, request: ImageGenRequest) -> ImageResult:
        raise ProviderNotImplemented(
            "GeminiImageProvider.generate реализуется в пункте «Подключение editing-API» "
            "(docs/plan.md, Этап 0)"
        )

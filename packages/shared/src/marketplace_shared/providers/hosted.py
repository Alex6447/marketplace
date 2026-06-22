"""Hosted-провайдеры (внешние API).

- `AnthropicLLMProvider` — реализован: вызовы Claude API через официальный SDK
  (async-клиент), structured-вывод по JSON Schema (`output_config.format`),
  адаптивное мышление по умолчанию. Модель по умолчанию — claude-opus-4-8.
- `GeminiImageProvider` — каркас: конфиг и ключ читаются, сами вызовы наполняются
  в пункте «Подключение editing-API» (docs/plan.md, Этап 0) и пока поднимают
  `ProviderNotImplemented`.

Заметки по Claude API (важно для корректности на Opus 4.8):
- sampling-параметры (`temperature`/`top_p`/`top_k`) удалены и приводят к 400 —
  поэтому `LLMRequest.temperature` сюда НЕ передаётся;
- мышление — только адаптивное (`thinking={"type": "adaptive"}`); `budget_tokens`
  приводит к 400;
- при `response_schema` ответ гарантированно валиден по схеме (первый text-блок —
  корректный JSON), его и разбираем.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .base import ImageProvider, LLMProvider
from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageResult,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    Usage,
)
from .errors import ProviderError, ProviderNotConfigured, ProviderNotImplemented

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"


def _split_messages(messages: list[LLMMessage]) -> tuple[str | None, list[dict[str, str]]]:
    """Разнести сообщения на `system` (отдельный параметр Claude) и диалог user/assistant."""
    system_parts: list[str] = []
    conversation: list[dict[str, str]] = []
    for message in messages:
        if message.role == "system":
            system_parts.append(message.content)
        else:
            conversation.append({"role": message.role, "content": message.content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, conversation


class AnthropicLLMProvider(LLMProvider):
    """LLM через Claude API (hosted)."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None = None,
        use_adaptive_thinking: bool = True,
    ) -> None:
        if not api_key:
            raise ProviderNotConfigured("Для провайдера 'anthropic' не задан ANTHROPIC_API_KEY")
        self._model = model or DEFAULT_ANTHROPIC_MODEL
        self._use_adaptive_thinking = use_adaptive_thinking
        # Конструктор клиента не делает сетевых вызовов.
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    def _build_kwargs(self, request: LLMRequest) -> dict[str, Any]:
        """Собрать аргументы для `messages.create`. Чистая функция — удобно тестировать."""
        system, conversation = _split_messages(request.messages)
        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "max_tokens": request.max_tokens,
            "messages": conversation,
        }
        if system:
            kwargs["system"] = system
        if self._use_adaptive_thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        # temperature намеренно НЕ передаём: Opus 4.8 отвергает sampling-параметры (400).
        if request.response_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": request.response_schema}
            }
        return kwargs

    def _parse_response(self, response: Any, response_schema: dict[str, Any] | None) -> LLMResponse:
        """Преобразовать ответ SDK в `LLMResponse`. Чистая функция — тестируется на фейках."""
        if response.stop_reason == "refusal":
            raise ProviderError(
                f"Claude отклонил запрос (refusal): {getattr(response, 'stop_details', None)}"
            )
        text = next(
            (b.text for b in response.content if getattr(b, "type", None) == "text"),
            "",
        )

        data: dict[str, Any] | None = None
        if response_schema is not None:
            if response.stop_reason == "max_tokens":
                raise ProviderError(
                    "ответ Claude обрезан по max_tokens — structured JSON неполный; "
                    "увеличьте max_tokens"
                )
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ProviderError(f"не удалось разобрать JSON из ответа Claude: {exc}") from exc

        u = response.usage
        cache = {
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None),
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None),
        }
        usage = Usage(
            input_tokens=getattr(u, "input_tokens", None),
            output_tokens=getattr(u, "output_tokens", None),
            extra={k: v for k, v in cache.items() if v},
        )
        return LLMResponse(
            text=text,
            data=data,
            provider=self.name,
            model=response.model,
            usage=usage,
            raw={"stop_reason": response.stop_reason},
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        kwargs = self._build_kwargs(request)
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            raise ProviderError(f"ошибка Claude API: {exc}") from exc
        return self._parse_response(response, request.response_schema)


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

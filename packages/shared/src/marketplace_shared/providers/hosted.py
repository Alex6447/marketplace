"""Hosted-провайдеры (внешние API).

- `AnthropicLLMProvider` — вызовы Claude API через официальный SDK (async-клиент),
  structured-вывод по JSON Schema (`output_config.format`), адаптивное мышление по
  умолчанию. Модель по умолчанию — claude-opus-4-8.
- `GeminiImageProvider` — editing-модель через Gemini API (`gemini-2.5-flash-image`)
  на официальном SDK `google-genai` (async-клиент `client.aio`). Реализует основной
  режим стадии [5] «оставь товар, измени фон/сцену» (`edit`) и генерацию фона с нуля
  (`generate`).

Заметки по Claude API (важно для корректности на Opus 4.8):
- sampling-параметры (`temperature`/`top_p`/`top_k`) удалены и приводят к 400 —
  поэтому `LLMRequest.temperature` сюда НЕ передаётся;
- мышление — только адаптивное (`thinking={"type": "adaptive"}`); `budget_tokens`
  приводит к 400;
- при `response_schema` ответ гарантированно валиден по схеме (первый text-блок —
  корректный JSON), его и разбираем.

Заметки по Gemini Image API:
- вход — мультимодальные `contents`: инструкция (текст) + входные изображения как
  `types.Part.from_bytes(data=, mime_type=)`; модель возвращает изображение
  inline-байтами в `candidates[0].content.parts[].inline_data`;
- изображения в `ImageRef` приходят либо inline (`data`), либо ссылкой (`url`,
  типичный случай — presigned MinIO/S3): url мы скачиваем сами (httpx), т.к. SDK
  принимает только Files-API URI, а не произвольный http;
- блокировки безопасности отражаются в `prompt_feedback.block_reason` (промт) и
  `finish_reason` кандидата (ответ) — оба маппим в `ProviderError`.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from .base import ImageProvider, LLMProvider
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
from .errors import ProviderError, ProviderNotConfigured

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
    """Editing-модель через Gemini API (hosted, `gemini-2.5-flash-image`)."""

    name = "gemini"

    def __init__(self, *, api_key: str | None, model: str | None = None) -> None:
        if not api_key:
            raise ProviderNotConfigured("Для провайдера 'gemini' не задан GEMINI_API_KEY")
        self._model = model or DEFAULT_GEMINI_IMAGE_MODEL
        # Конструктор клиента не делает сетевых вызовов.
        self._client = genai.Client(api_key=api_key)

    async def _resolve(self, ref: ImageRef) -> tuple[bytes, str]:
        """Получить байты и MIME изображения: из inline-данных или скачать по URL.

        SDK Gemini принимает inline-байты (`Part.from_bytes`) либо Files-API URI, но
        не произвольный http, поэтому presigned-ссылки MinIO/S3 скачиваем сами.
        """
        if ref.data is not None:
            return ref.data, ref.media_type
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ref.url)  # type: ignore[arg-type]  # url задан (валидатор ImageRef)
            response.raise_for_status()
        media_type = response.headers.get("content-type", ref.media_type) or ref.media_type
        return response.content, media_type

    @staticmethod
    def _build_contents(instruction: str, image_parts: list[Any]) -> list[Any]:
        """Собрать мультимодальный `contents`: инструкция + входные изображения.

        Чистая функция — удобно проверять состав запроса без сетевого вызова.
        """
        return [instruction, *image_parts]

    @staticmethod
    def _build_config(seed: int | None) -> Any | None:
        """Конфиг вызова. Прокидываем только `seed` (для воспроизводимости)."""
        if seed is None:
            return None
        return genai_types.GenerateContentConfig(seed=seed)

    def _parse_response(self, response: Any, model: str) -> ImageResult:
        """Преобразовать ответ SDK в `ImageResult`. Чистая функция — тестируется на фейках."""
        feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(feedback, "block_reason", None)
        if block_reason:
            raise ProviderError(f"Gemini заблокировал запрос (prompt): {block_reason}")

        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            raise ProviderError("Gemini не вернул ни одного кандидата")
        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        content = getattr(candidate, "content", None)
        parts = (getattr(content, "parts", None) or []) if content is not None else []

        image_ref: ImageRef | None = None
        texts: list[str] = []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if image_ref is None and inline is not None and getattr(inline, "data", None):
                image_ref = ImageRef(
                    data=inline.data,
                    media_type=getattr(inline, "mime_type", None) or "image/png",
                )
            text = getattr(part, "text", None)
            if text:
                texts.append(text)

        if image_ref is None:
            raise ProviderError(
                f"Gemini не вернул изображение (finish_reason={finish_reason}); "
                f"текст ответа: {' '.join(texts) or '—'}"
            )

        return ImageResult(
            image=image_ref,
            provider=self.name,
            model=getattr(response, "model_version", None) or model,
            usage=_map_gemini_usage(response),
            raw={
                "finish_reason": str(finish_reason) if finish_reason is not None else None,
                "text": " ".join(texts) or None,
            },
        )

    async def _call(self, model: str | None, contents: list[Any], seed: int | None) -> ImageResult:
        target_model = model or self._model
        try:
            response = await self._client.aio.models.generate_content(
                model=target_model,
                contents=contents,
                config=self._build_config(seed),
            )
        except genai_errors.APIError as exc:
            raise ProviderError(f"ошибка Gemini API: {exc}") from exc
        return self._parse_response(response, target_model)

    def _image_part(self, data: bytes, media_type: str) -> Any:
        return genai_types.Part.from_bytes(data=data, mime_type=media_type)

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        # Основной режим [5]: товар сохраняется, меняется фон/сцена по инструкции.
        image_data, image_mime = await self._resolve(request.image)
        parts = [self._image_part(image_data, image_mime)]
        for ref in request.references:
            ref_data, ref_mime = await self._resolve(ref)
            parts.append(self._image_part(ref_data, ref_mime))
        contents = self._build_contents(request.instruction, parts)
        return await self._call(request.model, contents, request.seed)

    async def generate(self, request: ImageGenRequest) -> ImageResult:
        # Генерация с нуля (например, фон/сцена для композитинга).
        parts: list[Any] = []
        for ref in request.references:
            ref_data, ref_mime = await self._resolve(ref)
            parts.append(self._image_part(ref_data, ref_mime))
        contents = self._build_contents(request.prompt, parts)
        return await self._call(request.model, contents, request.seed)


def _map_gemini_usage(response: Any) -> Usage:
    """Извлечь учёт токенов из `usage_metadata` ответа Gemini (если есть)."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return Usage(extra={"images": 1})
    extra: dict[str, Any] = {"images": 1}
    total = getattr(meta, "total_token_count", None)
    if total is not None:
        extra["total_token_count"] = total
    return Usage(
        input_tokens=getattr(meta, "prompt_token_count", None),
        output_tokens=getattr(meta, "candidates_token_count", None),
        extra=extra,
    )

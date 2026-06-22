"""Офлайн-провайдеры `echo` — рабочий дефолт без сети, ключей и расходов.

Назначение:
- прогон пайплайна и тестов end-to-end без обращения к платным API;
- детерминированный вывод (удобно для ассертов);
- `EchoImageProvider.edit` возвращает товар 1:1 — наглядная модель главного
  инварианта проекта «товар сохраняется без искажений».

Это не мок в тестовом смысле, а полноценная реализация интерфейса для режима «без
внешних моделей»; hosted-реализации живут в `hosted.py`.
"""

from __future__ import annotations

import json
from typing import Any

from .base import ImageProvider, LLMProvider
from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageRef,
    ImageResult,
    LLMRequest,
    LLMResponse,
    Usage,
)


def _stub_from_schema(schema: dict[str, Any]) -> Any:
    """Построить минимальную болванку, валидную по (под)схеме JSON Schema.

    Поддерживает базовые конструкции (object/array/примитивы, enum, default). Этого
    достаточно, чтобы downstream-стадии получали структурно корректный JSON в офлайне.
    """
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    schema_type = schema.get("type")
    if isinstance(schema_type, list):  # напр. ["string", "null"]
        schema_type = next((t for t in schema_type if t != "null"), schema_type[0])

    if schema_type == "object" or "properties" in schema:
        props: dict[str, Any] = schema.get("properties", {})
        required = schema.get("required", list(props))
        return {key: _stub_from_schema(props[key]) for key in required if key in props}
    if schema_type == "array":
        items = schema.get("items")
        return [_stub_from_schema(items)] if isinstance(items, dict) else []
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "null":
        return None
    return ""  # string и неизвестные типы


def _last_user_message(request: LLMRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return ""


class EchoLLMProvider(LLMProvider):
    """Детерминированный LLM-заглушка: эхо запроса или болванка по схеме."""

    name = "echo"

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model or "echo-llm"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        prompt = _last_user_message(request)
        if request.response_schema is not None:
            data = _stub_from_schema(request.response_schema)
            text = json.dumps(data, ensure_ascii=False)
        else:
            data = None
            text = f"[echo] {prompt}"
        usage = Usage(input_tokens=len(prompt.split()), output_tokens=len(text.split()))
        return LLMResponse(
            text=text,
            data=data,
            provider=self.name,
            model=self._model,
            usage=usage,
            raw={"echo": True},
        )


class EchoImageProvider(ImageProvider):
    """Image-заглушка: `edit` сохраняет товар 1:1, `generate` отдаёт echo-ссылку."""

    name = "echo"

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model or "echo-image"

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        # Инвариант проекта в чистом виде: товар возвращается без изменений.
        return ImageResult(
            image=request.image.model_copy(deep=True),
            provider=self.name,
            model=self._model,
            usage=Usage(extra={"images": 1}),
            raw={"echo": True, "instruction": request.instruction},
        )

    async def generate(self, request: ImageGenRequest) -> ImageResult:
        ref = ImageRef(url=f"echo://generated?seed={request.seed}")
        return ImageResult(
            image=ref,
            provider=self.name,
            model=self._model,
            usage=Usage(extra={"images": 1}),
            raw={"echo": True, "prompt": request.prompt},
        )

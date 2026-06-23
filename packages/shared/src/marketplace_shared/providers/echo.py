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

import io
import json
from typing import Any

from PIL import Image

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


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    """Разрешить локальную ссылку JSON Schema (`#/$defs/Name`) относительно корня."""
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _stub_from_schema(schema: dict[str, Any], root: dict[str, Any] | None = None) -> Any:
    """Построить минимальную болванку, валидную по (под)схеме JSON Schema.

    Поддерживает базовые конструкции (object/array/примитивы, enum, default) и
    локальные ссылки `$ref` (`#/$defs/...`) — Pydantic строит вложенные модели
    через них. `root` — корневая схема для резолва ссылок (по умолчанию сама схема).
    Этого достаточно, чтобы downstream-стадии получали структурно корректный JSON
    в офлайне.
    """
    if root is None:
        root = schema
    if "$ref" in schema:
        return _stub_from_schema(_resolve_ref(schema["$ref"], root), root)
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
        return {key: _stub_from_schema(props[key], root) for key in required if key in props}
    if schema_type == "array":
        items = schema.get("items")
        return [_stub_from_schema(items, root)] if isinstance(items, dict) else []
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
    """Image-заглушка: `edit` сохраняет товар 1:1, `generate` отдаёт сплошной фон."""

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
        # Детерминированный плейсхолдер-фон реальными байтами: позволяет гонять
        # композитинг стадии [5] офлайн (вырез товара кладётся поверх этого фона).
        width, height = _parse_size(request.size)
        seed = request.seed or 0
        color = (210 - seed % 40, 214 - seed % 30, 222 - seed % 20)  # светлый нейтральный
        ref = ImageRef(data=_solid_png(width, height, color), media_type="image/png")
        return ImageResult(
            image=ref,
            provider=self.name,
            model=self._model,
            usage=Usage(extra={"images": 1}),
            raw={"echo": True, "prompt": request.prompt},
        )


def _parse_size(size: str | None, *, default: int = 1024) -> tuple[int, int]:
    """Разобрать строку размера вида "ШxВ" (например "1024x768"); иначе — квадрат default."""
    if size:
        try:
            w, h = (int(part) for part in size.lower().split("x", 1))
            return w, h
        except ValueError:
            pass
    return default, default


def _solid_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    """Сплошной PNG заданного размера и цвета (плейсхолдер-фон echo-провайдера)."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()

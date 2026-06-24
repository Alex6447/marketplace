"""Локальный LLM-провайдер на Ollama — Этап 6 (приватность/офлайн стадий [2]/[3]/[9]).

Реализует `LLMProvider` поверх HTTP-API локального Ollama (`/api/chat`), не таща ML в
пакет `shared`/тонкий API. Структурированный вывод (стадии [2] идеи, [3] концепции,
[9] разбор фидбэка) — через нативный режим Ollama `format=<JSON Schema>`: модель отдаёт
JSON, валидный по схеме (grammar-constrained decoding). Это та же роль, что у hosted
Claude в `AnthropicLLMProvider`, но локально (vLLM/Ollama, docs/plan.md 4.1).

Развёртывание стенда — см. память `comfyui-local-stack` (на той же машине Ollama;
порт по умолчанию 11434 на Windows может попадать в зарезервированный диапазон —
тогда используется альтернативный, напр. 11500, через `OLLAMA_URL`).
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

import httpx

from .base import LLMProvider
from .contracts import LLMRequest, LLMResponse, Usage
from .errors import ProviderError

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(content: str) -> dict[str, Any]:
    """Достать JSON-объект из ответа модели устойчиво к ```-ограждениям/преамбуле.

    Сначала пробуем распарсить как есть (нормальный путь при grammar-enforced выводе);
    затем — содержимое markdown-фенса; затем — первый блок от `{` до парной `}`.
    """
    for candidate in _json_candidates(content):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ProviderError(f"Ollama: не удалось извлечь JSON из ответа: {content[:200]!r}")


def _json_candidates(content: str) -> list[str]:
    candidates = [content.strip()]
    fence = _FENCE_RE.search(content)
    if fence:
        candidates.append(fence.group(1).strip())
    start, end = content.find("{"), content.rfind("}")
    if 0 <= start < end:
        candidates.append(content[start : end + 1])
    return candidates


class OllamaLLMProvider(LLMProvider):
    """LLM-провайдер поверх локального Ollama (структурный вывод через format=schema)."""

    name: ClassVar[str] = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:7b",
        timeout: float = 300.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        """Собрать тело /api/chat (чистая функция — проверяется без сети).

        `think` НЕ выставляем: на «думающих» моделях он отключает grammar-enforcement
        схемы; вместо этого закладываем запас токенов (num_predict=max_tokens).
        """
        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.response_schema is not None:
            payload["format"] = request.response_schema
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._model
        payload = self.build_payload(request, model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama: сервер недоступен или вернул ошибку: {exc}") from exc

        body = response.json()
        content = (body.get("message") or {}).get("content", "") or ""
        data = _extract_json(content) if request.response_schema is not None else None
        return LLMResponse(
            text=content,
            data=data,
            provider=self.name,
            model=body.get("model", model),
            usage=Usage(
                input_tokens=body.get("prompt_eval_count"),
                output_tokens=body.get("eval_count"),
                extra={"done_reason": body.get("done_reason")},
            ),
            raw={"done_reason": body.get("done_reason")},
        )

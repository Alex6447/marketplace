"""Офлайн-тесты локального Ollama LLM-провайдера (без сети).

Покрывают регистрацию, сборку тела /api/chat (в т.ч. format=schema) и устойчивое
извлечение JSON из ответа модели (``` -ограждения, преамбула). Реальный вызов
`complete` требует запущенного Ollama и здесь не проверяется.
"""

from __future__ import annotations

import pytest

from marketplace_shared.providers.config import ProviderSettings
from marketplace_shared.providers.contracts import LLMMessage, LLMRequest
from marketplace_shared.providers.errors import ProviderError
from marketplace_shared.providers.ollama import OllamaLLMProvider, _extract_json
from marketplace_shared.providers.registry import (
    available_llm_providers,
    get_llm_provider,
)

_SCHEMA = {
    "type": "object",
    "properties": {"role": {"type": "string"}},
    "required": ["role"],
}


def test_registered_in_registry() -> None:
    assert "ollama" in available_llm_providers()
    provider = get_llm_provider(ProviderSettings(llm_provider="ollama"))
    assert isinstance(provider, OllamaLLMProvider)
    assert provider.name == "ollama"


def test_settings_propagate() -> None:
    settings = ProviderSettings(
        llm_provider="ollama",
        ollama_url="http://host:11500/",
        ollama_model="gemma4:latest",
    )
    provider = get_llm_provider(settings)
    assert provider._base_url == "http://host:11500"  # хвостовой слэш срезан
    assert provider._model == "gemma4:latest"


def test_llm_model_overrides_ollama_model() -> None:
    settings = ProviderSettings(
        llm_provider="ollama", ollama_model="qwen2.5:7b", llm_model="llama3.1:8b"
    )
    assert get_llm_provider(settings)._model == "llama3.1:8b"


def test_build_payload_structured() -> None:
    provider = OllamaLLMProvider()
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="привет")],
        max_tokens=1500,
        temperature=0.3,
        response_schema=_SCHEMA,
    )
    payload = provider.build_payload(request, "gemma4:latest")
    assert payload["model"] == "gemma4:latest"
    assert payload["stream"] is False
    assert payload["format"] == _SCHEMA
    assert payload["options"] == {"temperature": 0.3, "num_predict": 1500}
    assert "think" not in payload  # think ломает grammar-enforcement схемы


def test_build_payload_plain_has_no_format() -> None:
    provider = OllamaLLMProvider()
    request = LLMRequest(messages=[LLMMessage(role="user", content="hi")])
    payload = provider.build_payload(request, "m")
    assert "format" not in payload


@pytest.mark.parametrize(
    "content",
    [
        '{"role": "cover"}',
        '```json\n{"role": "cover"}\n```',
        'Вот ответ:\n```\n{"role": "cover"}\n```\nготово',
        'Преамбула {"role": "cover"} хвост',
    ],
)
def test_extract_json_variants(content: str) -> None:
    assert _extract_json(content) == {"role": "cover"}


def test_extract_json_failure() -> None:
    with pytest.raises(ProviderError):
        _extract_json("совсем не json")

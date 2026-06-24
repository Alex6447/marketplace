"""Фабрики провайдеров: выбор реализации по конфигурации.

`get_llm_provider` / `get_image_provider` — единственная точка, где имя из конфига
(`LLM_PROVIDER`/`IMAGE_PROVIDER`) превращается в конкретную реализацию. Пайплайн
зовёт только их и работает с интерфейсами `LLMProvider`/`ImageProvider`.

Регистрация — явный словарь builder-функций (без импортных side effects): добавление
нового провайдера = одна строка здесь.
"""

from __future__ import annotations

from collections.abc import Callable

from .base import ImageProvider, LLMProvider, MattingProvider
from .comfyui import BiRefNetMattingProvider, ComfyUIImageProvider
from .config import ProviderSettings, get_provider_settings
from .echo import EchoImageProvider, EchoLLMProvider
from .errors import ProviderNotConfigured, ProviderNotImplemented
from .hosted import AnthropicLLMProvider, GeminiImageProvider
from .matting import SimpleMattingProvider
from .ollama import OllamaLLMProvider

LLMBuilder = Callable[[ProviderSettings], LLMProvider]
ImageBuilder = Callable[[ProviderSettings], ImageProvider]
MattingBuilder = Callable[[ProviderSettings], MattingProvider]


def _local_matting_not_implemented(name: str) -> MattingBuilder:
    """Builder-заглушка локальной matting-модели (BiRefNet/SAM2) — наполняется на Этапе 6."""

    def _build(_settings: ProviderSettings) -> MattingProvider:
        raise ProviderNotImplemented(
            f"Локальный matting-провайдер {name!r} (BiRefNet/SAM2) — Этап 6; "
            "для MVP используйте MATTING_PROVIDER='simple'"
        )

    return _build


_LLM_BUILDERS: dict[str, LLMBuilder] = {
    "echo": lambda s: EchoLLMProvider(model=s.llm_model),
    "anthropic": lambda s: AnthropicLLMProvider(api_key=s.anthropic_api_key, model=s.llm_model),
    "ollama": lambda s: OllamaLLMProvider(
        base_url=s.ollama_url, model=s.llm_model or s.ollama_model
    ),
}

_IMAGE_BUILDERS: dict[str, ImageBuilder] = {
    "echo": lambda s: EchoImageProvider(model=s.image_model),
    "gemini": lambda s: GeminiImageProvider(api_key=s.gemini_api_key, model=s.image_model),
    "comfyui": lambda s: ComfyUIImageProvider(
        base_url=s.comfyui_url,
        unet_name=s.comfyui_unet,
        t5_name=s.comfyui_t5,
        clip_l_name=s.comfyui_clip_l,
        vae_name=s.comfyui_vae,
        steps=s.comfyui_steps,
        guidance=s.comfyui_guidance,
        model=s.image_model,
    ),
}

_MATTING_BUILDERS: dict[str, MattingBuilder] = {
    "simple": lambda s: SimpleMattingProvider(model=s.matting_model),
    "birefnet": lambda s: BiRefNetMattingProvider(
        base_url=s.comfyui_url,
        model_name=s.matting_model or s.comfyui_birefnet_model,
    ),
    "sam2": _local_matting_not_implemented("sam2"),
}


def available_llm_providers() -> list[str]:
    """Имена зарегистрированных LLM-провайдеров."""
    return sorted(_LLM_BUILDERS)


def available_image_providers() -> list[str]:
    """Имена зарегистрированных image-провайдеров."""
    return sorted(_IMAGE_BUILDERS)


def available_matting_providers() -> list[str]:
    """Имена зарегистрированных matting-провайдеров."""
    return sorted(_MATTING_BUILDERS)


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


def get_matting_provider(settings: ProviderSettings | None = None) -> MattingProvider:
    """Создать matting-провайдера согласно конфигурации (`MATTING_PROVIDER`)."""
    settings = settings or get_provider_settings()
    try:
        builder = _MATTING_BUILDERS[settings.matting_provider]
    except KeyError:
        raise ProviderNotConfigured(
            f"Неизвестный MATTING_PROVIDER={settings.matting_provider!r}; "
            f"доступны: {available_matting_providers()}"
        ) from None
    return builder(settings)

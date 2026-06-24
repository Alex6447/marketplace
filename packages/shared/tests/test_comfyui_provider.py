"""Офлайн-тесты локального ComfyUI image-провайдера (без сети).

Покрывают регистрацию в реестре, разбор размера и чистое построение workflow-графов
Flux Kontext (edit) и Flux txt2img (generate). Реальные сетевые вызовы (`edit`/`generate`)
требуют запущенного ComfyUI и здесь не проверяются.
"""

from __future__ import annotations

import pytest

from marketplace_shared.providers.comfyui import ComfyUIImageProvider, _parse_size
from marketplace_shared.providers.config import ProviderSettings
from marketplace_shared.providers.errors import ProviderError
from marketplace_shared.providers.registry import (
    available_image_providers,
    get_image_provider,
)


def test_registered_in_registry() -> None:
    assert "comfyui" in available_image_providers()
    provider = get_image_provider(ProviderSettings(image_provider="comfyui"))
    assert isinstance(provider, ComfyUIImageProvider)
    assert provider.name == "comfyui"


def test_settings_propagate_to_provider() -> None:
    settings = ProviderSettings(
        image_provider="comfyui",
        comfyui_url="http://example:9999/",
        comfyui_unet="custom.gguf",
        comfyui_steps=8,
    )
    provider = get_image_provider(settings)
    assert provider._base_url == "http://example:9999"  # хвостовой слэш срезан
    assert provider._unet == "custom.gguf"
    assert provider._steps == 8


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("1024x1024", (1024, 1024)),
        ("1000x1500", (992, 1488)),  # округление вниз до кратного 16
        (None, (1024, 1024)),
    ],
)
def test_parse_size(size: str | None, expected: tuple[int, int]) -> None:
    assert _parse_size(size) == expected


def test_parse_size_invalid() -> None:
    with pytest.raises(ProviderError):
        _parse_size("не-размер")


def test_build_edit_workflow_structure() -> None:
    provider = ComfyUIImageProvider()
    wf = provider.build_edit_workflow("photo.png", "keep product, change background", 7)
    # GGUF-загрузчик модели и Kontext-специфичные узлы на месте.
    assert wf["unet"]["class_type"] == "UnetLoaderGGUF"
    assert wf["unet"]["inputs"]["unet_name"] == "flux1-kontext-dev-Q4_K_M.gguf"
    assert wf["clip"]["class_type"] == "DualCLIPLoaderGGUF"
    assert wf["scale"]["class_type"] == "FluxKontextImageScale"
    assert wf["ref"]["class_type"] == "ReferenceLatent"
    assert wf["img"]["inputs"]["image"] == "photo.png"
    assert wf["pos"]["inputs"]["text"] == "keep product, change background"
    assert wf["ksampler"]["inputs"]["seed"] == 7
    # Латент сэмплера — закодированный референс (denoise 1.0 по reference-conditioning).
    assert wf["ksampler"]["inputs"]["latent_image"] == ["enc", 0]


def test_build_generate_workflow_structure() -> None:
    provider = ComfyUIImageProvider()
    wf = provider.build_generate_workflow("warm studio scene", 1024, 768, 3)
    assert wf["latent"]["class_type"] == "EmptySD3LatentImage"
    assert wf["latent"]["inputs"] == {"width": 1024, "height": 768, "batch_size": 1}
    assert wf["pos"]["inputs"]["text"] == "warm studio scene"
    assert wf["ksampler"]["inputs"]["seed"] == 3
    # В txt2img нет узлов загрузки/кодирования входного изображения.
    assert "img" not in wf
    assert "scale" not in wf

"""Офлайн-тесты локального ComfyUI image-провайдера (без сети).

Покрывают регистрацию в реестре, разбор размера и чистое построение workflow-графов
Flux Kontext (edit) и Flux txt2img (generate). Реальные сетевые вызовы (`edit`/`generate`)
требуют запущенного ComfyUI и здесь не проверяются.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from marketplace_shared.providers.comfyui import (
    BiRefNetMattingProvider,
    ComfyUIImageProvider,
    _build_mask_and_cutout,
    _parse_size,
)
from marketplace_shared.providers.config import ProviderSettings
from marketplace_shared.providers.errors import ProviderError
from marketplace_shared.providers.registry import (
    available_image_providers,
    available_matting_providers,
    get_image_provider,
    get_matting_provider,
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


def test_birefnet_registered_in_registry() -> None:
    assert "birefnet" in available_matting_providers()
    provider = get_matting_provider(ProviderSettings(matting_provider="birefnet"))
    assert isinstance(provider, BiRefNetMattingProvider)
    assert provider.name == "birefnet"


def test_birefnet_model_from_settings() -> None:
    s = ProviderSettings(matting_provider="birefnet", matting_model="Matting")
    provider = get_matting_provider(s)
    assert provider._model_name == "Matting"  # matting_model имеет приоритет


def test_build_mask_workflow_structure() -> None:
    provider = BiRefNetMattingProvider()
    wf = provider.build_mask_workflow("photo.png")
    assert wf["model"]["class_type"] == "AutoDownloadBiRefNetModel"
    assert wf["model"]["inputs"]["model_name"] == "General"
    assert wf["mask"]["class_type"] == "GetMaskByBiRefNet"
    assert wf["mask"]["inputs"]["images"] == ["img", 0]
    assert wf["m2i"]["class_type"] == "MaskToImage"
    assert wf["save"]["inputs"]["images"] == ["m2i", 0]


def test_build_mask_and_cutout() -> None:
    # Источник 4×4 красный; маска: левая половина белая (товар), правая чёрная (фон).
    src = Image.new("RGB", (4, 4), (255, 0, 0))
    mask = Image.new("L", (4, 4), 0)
    for y in range(4):
        for x in range(2):
            mask.putpixel((x, y), 255)
    src_buf, mask_buf = io.BytesIO(), io.BytesIO()
    src.save(src_buf, format="PNG")
    mask.save(mask_buf, format="PNG")

    mask_norm, cutout = _build_mask_and_cutout(src_buf.getvalue(), mask_buf.getvalue())
    out = Image.open(io.BytesIO(cutout)).convert("RGBA")
    assert out.size == (4, 4)
    assert out.getpixel((0, 0))[3] == 255  # товар — непрозрачный
    assert out.getpixel((3, 0))[3] == 0  # фон — прозрачный
    assert Image.open(io.BytesIO(mask_norm)).mode == "L"

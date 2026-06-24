"""Локальные провайдеры на ComfyUI (Flux.1 Kontext + BiRefNet) — Этап 6.

Реализуют `ImageProvider` (стадия [5]) и `MattingProvider` (стадия [4]) поверх HTTP-API
локального сервера ComfyUI, не таща тяжёлые ML-зависимости (torch/ComfyUI) в пакет
`shared` или в тонкий API: общение идёт по сети (`/upload/image`, `/prompt`, `/history`,
`/view`). Это сохраняет провайдеро-независимость (docs_marketplace/plan.md, 4.1) — пайплайн зовёт
`edit`/`generate`/`remove_background`, не зная, что под капотом ComfyUI.

- `ComfyUIImageProvider.edit` — основной режим [5]: editing-модель Flux.1 Kontext по
  инструкции «оставь товар, измени фон/сцену» (граф: GGUF-загрузчики → VAEEncode →
  ReferenceLatent → FluxGuidance → KSampler → VAEDecode).
- `ComfyUIImageProvider.generate` — Flux txt2img с нуля (фон/сцена для композитинга [5]).
- `BiRefNetMattingProvider.remove_background` — стадия [4]: BiRefNet даёт качественную
  маску (в т.ч. сложные/прозрачные края), вырез RGBA собирается из маски на Pillow.

Модели и адрес сервера задаются конфигом (`COMFYUI_*`). Развёртывание стенда —
см. память `comfyui-local-stack` (D:\\AI\\ComfyUI на RTX 3060).
"""

from __future__ import annotations

import asyncio
import io
import uuid
from typing import Any, ClassVar

import httpx
from PIL import Image

from .base import ImageProvider, MattingProvider
from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageRef,
    ImageResult,
    MattingRequest,
    MattingResult,
    Usage,
)
from .errors import ProviderError


def _parse_size(size: str | None, default: int = 1024) -> tuple[int, int]:
    """Разобрать "WxH" → (width, height), округлив до кратного 16 (требование Flux)."""
    if not size:
        return default, default
    try:
        w_str, h_str = size.lower().split("x", 1)
        w, h = int(w_str), int(h_str)
    except (ValueError, AttributeError) as exc:
        raise ProviderError(f"ComfyUI: некорректный size={size!r}, ожидается 'WxH'") from exc
    round16 = lambda v: max(16, (v // 16) * 16)  # noqa: E731
    return round16(w), round16(h)


# --------------------------------------------------------------------------- #
# Общий HTTP-плумбинг ComfyUI (используется обоими провайдерами)
# --------------------------------------------------------------------------- #


async def _resolve_bytes(ref: ImageRef, client: httpx.AsyncClient) -> bytes:
    """Получить байты изображения из ImageRef: inline или скачать по URL."""
    if ref.data is not None:
        return ref.data
    response = await client.get(ref.url)  # type: ignore[arg-type]  # url задан валидатором
    response.raise_for_status()
    return response.content


async def _upload_image(base_url: str, data: bytes, client: httpx.AsyncClient) -> str:
    """Загрузить изображение в ComfyUI (папка input) → вернуть имя файла."""
    filename = f"mp_{uuid.uuid4().hex}.png"
    files = {"image": (filename, data, "image/png")}
    form = {"type": "input", "overwrite": "true"}
    try:
        response = await client.post(f"{base_url}/upload/image", files=files, data=form)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"ComfyUI: ошибка загрузки изображения: {exc}") from exc
    return response.json().get("name", filename)


async def _wait_history(
    base_url: str, prompt_id: str, client: httpx.AsyncClient, timeout: float, poll: float
) -> dict[str, Any]:
    """Опрашивать /history/{id} до появления записи или таймаута."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            response = await client.get(f"{base_url}/history/{prompt_id}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ComfyUI: ошибка опроса истории: {exc}") from exc
        record = response.json().get(prompt_id)
        if record:
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise ProviderError(f"ComfyUI: выполнение графа завершилось ошибкой: {status}")
            return record
        if asyncio.get_event_loop().time() > deadline:
            raise ProviderError(f"ComfyUI: таймаут ожидания результата ({timeout}с)")
        await asyncio.sleep(poll)


async def _fetch_first_image(
    base_url: str, record: dict[str, Any], client: httpx.AsyncClient
) -> bytes:
    """Найти первое выходное изображение в истории и скачать его через /view."""
    for node_out in record.get("outputs", {}).values():
        for img in node_out.get("images", []):
            params = {
                "filename": img["filename"],
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
            }
            try:
                response = await client.get(f"{base_url}/view", params=params)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(f"ComfyUI: не удалось скачать результат: {exc}") from exc
            return response.content
    raise ProviderError("ComfyUI: граф не вернул ни одного изображения")


async def _run_workflow_image(
    base_url: str,
    workflow: dict[str, Any],
    client: httpx.AsyncClient,
    *,
    timeout: float,
    poll: float,
) -> tuple[bytes, str]:
    """Поставить workflow, дождаться выполнения, вернуть (байты первого изображения, prompt_id)."""
    client_id = uuid.uuid4().hex
    try:
        response = await client.post(
            f"{base_url}/prompt", json={"prompt": workflow, "client_id": client_id}
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"ComfyUI: сервер недоступен или отверг запрос: {exc}") from exc
    body = response.json()
    if body.get("node_errors"):
        raise ProviderError(f"ComfyUI: ошибки нод графа: {body['node_errors']}")
    prompt_id = body.get("prompt_id")
    if not prompt_id:
        raise ProviderError(f"ComfyUI: не вернул prompt_id: {body}")
    record = await _wait_history(base_url, prompt_id, client, timeout, poll)
    image_bytes = await _fetch_first_image(base_url, record, client)
    return image_bytes, prompt_id


# --------------------------------------------------------------------------- #
# Image-провайдер (стадия [5])
# --------------------------------------------------------------------------- #


class ComfyUIImageProvider(ImageProvider):
    """Image-провайдер поверх локального ComfyUI (Flux.1 Kontext / Flux txt2img)."""

    name: ClassVar[str] = "comfyui"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8188",
        unet_name: str = "flux1-kontext-dev-Q4_K_M.gguf",
        t5_name: str = "t5-v1_1-xxl-encoder-Q5_K_M.gguf",
        clip_l_name: str = "clip_l.safetensors",
        vae_name: str = "ae.safetensors",
        steps: int = 20,
        guidance: float = 2.5,
        sampler: str = "euler",
        scheduler: str = "simple",
        model: str | None = None,
        timeout: float = 600.0,
        poll_interval: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._unet = model or unet_name
        self._t5 = t5_name
        self._clip_l = clip_l_name
        self._vae = vae_name
        self._steps = steps
        self._guidance = guidance
        self._sampler = sampler
        self._scheduler = scheduler
        self._timeout = timeout
        self._poll_interval = poll_interval

    def _loaders(self) -> dict[str, Any]:
        """Общие узлы загрузки модели/энкодеров/VAE для обоих графов."""
        return {
            "unet": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": self._unet}},
            "clip": {
                "class_type": "DualCLIPLoaderGGUF",
                "inputs": {"clip_name1": self._t5, "clip_name2": self._clip_l, "type": "flux"},
            },
            "vae": {"class_type": "VAELoader", "inputs": {"vae_name": self._vae}},
        }

    def build_edit_workflow(
        self, image_filename: str, instruction: str, seed: int
    ) -> dict[str, Any]:
        """Граф Flux Kontext: товар сохраняется, фон меняется по инструкции."""
        nodes = self._loaders()
        nodes.update(
            {
                "img": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
                "scale": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["img", 0]}},
                "enc": {
                    "class_type": "VAEEncode",
                    "inputs": {"pixels": ["scale", 0], "vae": ["vae", 0]},
                },
                "pos": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"clip": ["clip", 0], "text": instruction},
                },
                "ref": {
                    "class_type": "ReferenceLatent",
                    "inputs": {"conditioning": ["pos", 0], "latent": ["enc", 0]},
                },
                "guid": {
                    "class_type": "FluxGuidance",
                    "inputs": {"conditioning": ["ref", 0], "guidance": self._guidance},
                },
                "neg": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"clip": ["clip", 0], "text": ""},
                },
                "ksampler": {
                    "class_type": "KSampler",
                    "inputs": {
                        "model": ["unet", 0],
                        "positive": ["guid", 0],
                        "negative": ["neg", 0],
                        "latent_image": ["enc", 0],
                        "seed": seed,
                        "steps": self._steps,
                        "cfg": 1.0,
                        "sampler_name": self._sampler,
                        "scheduler": self._scheduler,
                        "denoise": 1.0,
                    },
                },
                "dec": {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": ["ksampler", 0], "vae": ["vae", 0]},
                },
                "save": {
                    "class_type": "SaveImage",
                    "inputs": {"images": ["dec", 0], "filename_prefix": "mp_edit"},
                },
            }
        )
        return nodes

    def build_generate_workflow(
        self, prompt: str, width: int, height: int, seed: int
    ) -> dict[str, Any]:
        """Граф Flux txt2img: генерация фона/сцены с нуля (для композитинга)."""
        nodes = self._loaders()
        nodes.update(
            {
                "latent": {
                    "class_type": "EmptySD3LatentImage",
                    "inputs": {"width": width, "height": height, "batch_size": 1},
                },
                "pos": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"clip": ["clip", 0], "text": prompt},
                },
                "guid": {
                    "class_type": "FluxGuidance",
                    "inputs": {"conditioning": ["pos", 0], "guidance": self._guidance},
                },
                "neg": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"clip": ["clip", 0], "text": ""},
                },
                "ksampler": {
                    "class_type": "KSampler",
                    "inputs": {
                        "model": ["unet", 0],
                        "positive": ["guid", 0],
                        "negative": ["neg", 0],
                        "latent_image": ["latent", 0],
                        "seed": seed,
                        "steps": self._steps,
                        "cfg": 1.0,
                        "sampler_name": self._sampler,
                        "scheduler": self._scheduler,
                        "denoise": 1.0,
                    },
                },
                "dec": {
                    "class_type": "VAEDecode",
                    "inputs": {"samples": ["ksampler", 0], "vae": ["vae", 0]},
                },
                "save": {
                    "class_type": "SaveImage",
                    "inputs": {"images": ["dec", 0], "filename_prefix": "mp_bg"},
                },
            }
        )
        return nodes

    async def _run(self, workflow: dict[str, Any], client: httpx.AsyncClient) -> ImageResult:
        image_bytes, prompt_id = await _run_workflow_image(
            self._base_url, workflow, client, timeout=self._timeout, poll=self._poll_interval
        )
        return ImageResult(
            image=ImageRef(data=image_bytes, media_type="image/png"),
            provider=self.name,
            model=self._unet,
            usage=Usage(extra={"images": 1, "steps": self._steps}),
            raw={"prompt_id": prompt_id},
        )

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        # Референсы сцены пока не поддержаны локально (Kontext-стичинг — позже);
        # сохранность товара обеспечивает основное фото-референс.
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            image_data = await _resolve_bytes(request.image, client)
            filename = await _upload_image(self._base_url, image_data, client)
            workflow = self.build_edit_workflow(filename, request.instruction, request.seed or 0)
            return await self._run(workflow, client)

    async def generate(self, request: ImageGenRequest) -> ImageResult:
        width, height = _parse_size(request.size)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            workflow = self.build_generate_workflow(
                request.prompt, width, height, request.seed or 0
            )
            return await self._run(workflow, client)


# --------------------------------------------------------------------------- #
# Matting-провайдер (стадия [4]) — BiRefNet через ComfyUI
# --------------------------------------------------------------------------- #


def _build_mask_and_cutout(source_png: bytes, mask_png: bytes) -> tuple[bytes, bytes]:
    """Из исходного фото и маски BiRefNet собрать (нормализованную маску L, вырез RGBA).

    Чистая функция на Pillow: маска приводится к grayscale (белое=товар), вырез — копия
    исходника с alpha-каналом из маски (прозрачный фон) — контракт `MattingResult`.
    """
    src = Image.open(io.BytesIO(source_png)).convert("RGBA")
    mask = Image.open(io.BytesIO(mask_png)).convert("L")
    if mask.size != src.size:
        mask = mask.resize(src.size)
    cutout = src.copy()
    cutout.putalpha(mask)
    mask_buf, cut_buf = io.BytesIO(), io.BytesIO()
    mask.save(mask_buf, format="PNG")
    cutout.save(cut_buf, format="PNG")
    return mask_buf.getvalue(), cut_buf.getvalue()


class BiRefNetMattingProvider(MattingProvider):
    """Matting-провайдер [4] на BiRefNet (нода ComfyUI_BiRefNet_ll) через ComfyUI-API.

    BiRefNet — SOTA по краям (волосы, стекло, прозрачная упаковка), в отличие от
    офлайн-кеинга `SimpleMattingProvider` (хорош только для непрозрачного товара на
    однотонном фоне). Веса авто-скачиваются нодой при первом вызове.
    """

    name: ClassVar[str] = "birefnet"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8188",
        model_name: str = "General",
        device: str = "AUTO",
        timeout: float = 600.0,
        poll_interval: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._device = device
        self._timeout = timeout
        self._poll_interval = poll_interval

    def build_mask_workflow(self, image_filename: str) -> dict[str, Any]:
        """Граф BiRefNet: фото → BIREFNET-модель → маска товара → image (для SaveImage)."""
        return {
            "model": {
                "class_type": "AutoDownloadBiRefNetModel",
                "inputs": {"model_name": self._model_name, "device": self._device},
            },
            "img": {"class_type": "LoadImage", "inputs": {"image": image_filename}},
            "mask": {
                "class_type": "GetMaskByBiRefNet",
                "inputs": {
                    "model": ["model", 0],
                    "images": ["img", 0],
                    "width": 1024,
                    "height": 1024,
                    "upscale_method": "bilinear",
                    "mask_threshold": 0.0,
                },
            },
            "m2i": {"class_type": "MaskToImage", "inputs": {"mask": ["mask", 0]}},
            "save": {
                "class_type": "SaveImage",
                "inputs": {"images": ["m2i", 0], "filename_prefix": "mp_mask"},
            },
        }

    async def remove_background(self, request: MattingRequest) -> MattingResult:
        model_name = request.model or self._model_name
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            source = await _resolve_bytes(request.image, client)
            filename = await _upload_image(self._base_url, source, client)
            workflow = self.build_mask_workflow(filename)
            workflow["model"]["inputs"]["model_name"] = model_name
            mask_png, prompt_id = await _run_workflow_image(
                self._base_url, workflow, client, timeout=self._timeout, poll=self._poll_interval
            )
        mask_norm, cutout = _build_mask_and_cutout(source, mask_png)
        return MattingResult(
            mask=ImageRef(data=mask_norm, media_type="image/png"),
            cutout=ImageRef(data=cutout, media_type="image/png"),
            provider=self.name,
            model=model_name,
            usage=Usage(extra={"images": 1}),
            raw={"prompt_id": prompt_id},
        )

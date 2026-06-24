"""Локальный image-провайдер на ComfyUI (Flux.1 Kontext, GGUF) — Этап 6.

Реализует `ImageProvider` поверх HTTP-API локального сервера ComfyUI, не таща тяжёлые
ML-зависимости (torch/ComfyUI) в пакет `shared` или в тонкий API: общение идёт по сети
(`/upload/image`, `/prompt`, `/history`, `/view`). Это сохраняет провайдеро-независимость
(docs/plan.md, 4.1) — пайплайн зовёт `edit`/`generate`, не зная, что под капотом ComfyUI.

- `edit` — основной режим [5]: editing-модель Flux.1 Kontext по инструкции «оставь товар,
  измени фон/сцену» с фото-референсом (граф: GGUF-загрузчики → VAEEncode → ReferenceLatent
  → FluxGuidance → KSampler → VAEDecode).
- `generate` — Flux txt2img с нуля (фон/сцена для композитинга [5]).

Модели и адрес сервера задаются конфигом (`COMFYUI_*`). Развёртывание стенда —
см. память `comfyui-local-stack` (D:\\AI\\ComfyUI на RTX 3060).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

import httpx

from .base import ImageProvider
from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageRef,
    ImageResult,
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

    # ------------------------------------------------------------------ #
    # Вспомогательные сетевые операции
    # ------------------------------------------------------------------ #

    async def _resolve_bytes(self, ref: ImageRef, client: httpx.AsyncClient) -> bytes:
        """Получить байты изображения из ImageRef: inline или скачать по URL."""
        if ref.data is not None:
            return ref.data
        response = await client.get(ref.url)  # type: ignore[arg-type]  # url задан валидатором
        response.raise_for_status()
        return response.content

    async def _upload_image(self, data: bytes, client: httpx.AsyncClient) -> str:
        """Загрузить изображение в ComfyUI (папка input) → вернуть имя файла."""
        filename = f"mp_{uuid.uuid4().hex}.png"
        files = {"image": (filename, data, "image/png")}
        form = {"type": "input", "overwrite": "true"}
        try:
            response = await client.post(f"{self._base_url}/upload/image", files=files, data=form)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ComfyUI: ошибка загрузки изображения: {exc}") from exc
        return response.json().get("name", filename)

    async def _run_workflow(
        self, workflow: dict[str, Any], client: httpx.AsyncClient
    ) -> ImageResult:
        """Поставить workflow, дождаться выполнения и вернуть первое изображение."""
        client_id = uuid.uuid4().hex
        try:
            response = await client.post(
                f"{self._base_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ComfyUI: сервер недоступен или отверг запрос: {exc}") from exc

        body = response.json()
        node_errors = body.get("node_errors")
        if node_errors:
            raise ProviderError(f"ComfyUI: ошибки нод графа: {node_errors}")
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ProviderError(f"ComfyUI: не вернул prompt_id: {body}")

        record = await self._wait_history(prompt_id, client)
        image_bytes = await self._fetch_first_image(record, client)
        return ImageResult(
            image=ImageRef(data=image_bytes, media_type="image/png"),
            provider=self.name,
            model=self._unet,
            usage=Usage(extra={"images": 1, "steps": self._steps}),
            raw={"prompt_id": prompt_id},
        )

    async def _wait_history(self, prompt_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
        """Опрашивать /history/{id} до появления записи или таймаута."""
        deadline = asyncio.get_event_loop().time() + self._timeout
        while True:
            try:
                response = await client.get(f"{self._base_url}/history/{prompt_id}")
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
                raise ProviderError(f"ComfyUI: таймаут ожидания результата ({self._timeout}с)")
            await asyncio.sleep(self._poll_interval)

    async def _fetch_first_image(
        self, record: dict[str, Any], client: httpx.AsyncClient
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
                    response = await client.get(f"{self._base_url}/view", params=params)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise ProviderError(f"ComfyUI: не удалось скачать результат: {exc}") from exc
                return response.content
        raise ProviderError("ComfyUI: граф не вернул ни одного изображения")

    # ------------------------------------------------------------------ #
    # Построение workflow-графов (чистые функции — проверяемы без сети)
    # ------------------------------------------------------------------ #

    def _loaders(self) -> dict[str, Any]:
        """Общие узлы загрузки модели/энкодеров/VAE для обоих графов."""
        return {
            "unet": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": self._unet}},
            "clip": {
                "class_type": "DualCLIPLoaderGGUF",
                "inputs": {
                    "clip_name1": self._t5,
                    "clip_name2": self._clip_l,
                    "type": "flux",
                },
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

    # ------------------------------------------------------------------ #
    # Реализация интерфейса ImageProvider
    # ------------------------------------------------------------------ #

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        # Референсы сцены пока не поддержаны локально (Kontext-стичинг — позже);
        # сохранность товара обеспечивает основное фото-референс.
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            image_data = await self._resolve_bytes(request.image, client)
            filename = await self._upload_image(image_data, client)
            workflow = self.build_edit_workflow(
                filename, request.instruction, request.seed or 0
            )
            return await self._run_workflow(workflow, client)

    async def generate(self, request: ImageGenRequest) -> ImageResult:
        width, height = _parse_size(request.size)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            workflow = self.build_generate_workflow(
                request.prompt, width, height, request.seed or 0
            )
            return await self._run_workflow(workflow, client)

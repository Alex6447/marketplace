"""Абстрактный интерфейс движка наложения текста (стадия [6]).

Аналог провайдер-абстракций (`LLMProvider`/`ImageProvider`): пайплайн зовёт только
:meth:`TextRenderer.render`, а конкретный backend (Playwright/Pillow) выбирается
реестром по конфигу — без правок стадии. Метод async для единообразия с остальным
пайплайном (Playwright по природе async; в Celery оборачивается ``asyncio.run``).
"""

from __future__ import annotations

import io
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx
from PIL import Image

from .contracts import Canvas, RenderRequest, RenderResult


class TextRenderer(ABC):
    """Детерминированное наложение текстовых блоков поверх изображения карточки."""

    #: Короткое имя рендерера (ключ в реестре: "pillow", "playwright").
    name: ClassVar[str]

    @abstractmethod
    async def render(self, request: RenderRequest) -> RenderResult:
        """Наложить текст и вернуть готовое изображение карточки (PNG)."""
        raise NotImplementedError

    async def _load_base(self, request: RenderRequest) -> Image.Image:
        """Загрузить базовое изображение (inline/URL) и привести к размеру холста.

        Общий помощник для backend'ов: разрешает :class:`ImageRef` и при заданном
        ``canvas`` масштабирует изображение под целевой размер (RGBA для композитинга).
        """
        data = await self._resolve(request.base_image)
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        if request.canvas is not None and (image.width, image.height) != (
            request.canvas.width,
            request.canvas.height,
        ):
            image = image.resize((request.canvas.width, request.canvas.height))
        return image

    @staticmethod
    def canvas_of(request: RenderRequest, image: Image.Image) -> Canvas:
        """Итоговый холст: из запроса или из размеров базового изображения."""
        return request.canvas or Canvas(width=image.width, height=image.height)

    @staticmethod
    async def _resolve(ref) -> bytes:
        """Байты изображения: inline-данные или скачивание по presigned-URL."""
        if ref.data is not None:
            return ref.data
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ref.url)
            response.raise_for_status()
        return response.content

"""Абстрактные интерфейсы провайдеров.

`LLMProvider` и `ImageProvider` — единственная точка, через которую пайплайн
обращается к генеративным моделям. Любой backend (hosted-API или локальная модель)
реализует эти ABC, и переключение режима (docs/plan.md, 4.1) сводится к подмене
реализации в фабрике (`registry.py`) без правок пайплайна.

Методы асинхронные: вызовы моделей — сетевой/IO-bound, это естественно для API на
FastAPI и для SSE-прогресса. В синхронном Celery-воркере оборачиваются `asyncio.run`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageResult,
    LLMRequest,
    LLMResponse,
)


class LLMProvider(ABC):
    """Генерация текста и структурированных JSON-концепций (стадии [2], [3], [9])."""

    #: Короткое имя провайдера (ключ в реестре, напр. "echo", "anthropic").
    name: ClassVar[str]

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Выполнить запрос к LLM и вернуть ответ (текст и/или structured `data`)."""
        raise NotImplementedError


class ImageProvider(ABC):
    """Генерация изображений с сохранением товара (стадия [5])."""

    name: ClassVar[str]

    @abstractmethod
    async def edit(self, request: ImageEditRequest) -> ImageResult:
        """Editing по инструкции с сохранением товара (основной режим)."""
        raise NotImplementedError

    @abstractmethod
    async def generate(self, request: ImageGenRequest) -> ImageResult:
        """Генерация изображения с нуля (например, фон/сцена для композитинга)."""
        raise NotImplementedError

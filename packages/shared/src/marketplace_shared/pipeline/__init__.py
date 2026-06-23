"""Стадии пайплайна генерации карточек (docs/plan.md, раздел 3).

Здесь живёт провайдеро-независимая бизнес-логика стадий: построение запроса к
модели, разбор и валидация результата в Pydantic-контракты. Стадии не знают, какой
провайдер их обслуживает (hosted/local) и кто их вызывает — синхронный API (Этап 1)
или Celery-воркер (Этап 2): на вход им передаётся готовый :class:`LLMProvider`/
:class:`ImageProvider`.

Стадия [2] «генерация идей» — в :mod:`marketplace_shared.pipeline.ideas`.
"""

from __future__ import annotations

from .ideas import (
    IdeaSlide,
    ProductBrief,
    ProductIdeas,
    build_ideas_request,
    generate_ideas,
)

__all__ = [
    "ProductBrief",
    "IdeaSlide",
    "ProductIdeas",
    "build_ideas_request",
    "generate_ideas",
]

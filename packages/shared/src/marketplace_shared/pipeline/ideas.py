"""Стадия [2] — генерация идей карточек (LLM). См. docs_marketplace/plan.md, разделы 3 и 6.

Вход: бриф товара (характеристики, преимущества, ЦА, требования) + стиль бренда.
Выход (structured JSON): план комплекта карточек — список слайдов с ролью, ключевыми
смыслами, акцентами и тоном. Этот результат — вход стадии [3] (визуальные концепции).

Контракт описан Pydantic-моделями: они же — единственный источник истины для JSON
Schema, которую мы отдаём LLM (`response_schema`), и для валидации её ответа. Логика
провайдеро-независима: на вход приходит готовый :class:`LLMProvider`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from marketplace_shared.providers.base import LLMProvider
from marketplace_shared.providers.contracts import LLMMessage, LLMRequest, LLMResponse
from marketplace_shared.providers.errors import ProviderError

# Рекомендованные роли слайдов (обложка/преимущества/сценарий/состав/гарантии…).
# Не enum: набор ролей зависит от товара и маркетплейса, модель вправе предложить
# свой; это подсказка в промте, а не жёсткое ограничение схемы.
RECOMMENDED_ROLES = (
    "cover",  # обложка
    "advantages",  # преимущества
    "usage",  # сценарий использования
    "composition",  # состав / материалы
    "specs",  # характеристики
    "guarantees",  # гарантии / сертификаты
    "lifestyle",  # товар в интерьере / на модели
    "comparison",  # сравнение / «было-стало»
)


# --------------------------------------------------------------------------- #
# Вход стадии
# --------------------------------------------------------------------------- #


class ProductBrief(BaseModel):
    """Сводка данных о товаре для генерации идей (собирается из ORM в API/воркере)."""

    title: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    advantages: str | None = None
    target_audience: str | None = None
    requirements: dict[str, Any] = Field(default_factory=dict)
    #: Описание стиля бренда (берётся из проекта) — тон и визуальные правила.
    brand_style: str | None = None


# --------------------------------------------------------------------------- #
# Контракт результата (он же — JSON Schema для LLM)
# --------------------------------------------------------------------------- #


class IdeaSlide(BaseModel):
    """Идея одного слайда карточки."""

    role: str = Field(
        description="Роль слайда: обложка/преимущества/сценарий/состав/гарантии и т.п."
    )
    title: str = Field(description="Короткий заголовок-идея слайда.")
    key_messages: list[str] = Field(
        description="Ключевые смыслы, которые доносит слайд (1–4 пункта)."
    )
    accents: list[str] = Field(
        default_factory=list,
        description="Визуальные/смысловые акценты слайда (что подчеркнуть).",
    )
    tone: str = Field(description="Тон подачи слайда (например: премиальный, дружелюбный).")


class ProductIdeas(BaseModel):
    """План комплекта карточек — результат стадии [2]."""

    slides: list[IdeaSlide] = Field(description="Слайды комплекта в порядке показа.")
    overall_tone: str = Field(description="Общий тон комплекта карточек.")
    notes: str | None = Field(
        default=None, description="Дополнительные замечания по комплекту (необязательно)."
    )


# Схема результата для structured-вывода LLM. Pydantic строит её с внутренними
# ссылками ($defs/$ref) — провайдеры (Claude) и echo-стаб их понимают.
IDEAS_RESPONSE_SCHEMA: dict[str, Any] = ProductIdeas.model_json_schema()


# --------------------------------------------------------------------------- #
# Построение запроса и вызов
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = (
    "Ты — арт-директор и маркетолог, который проектирует комплекты продающих "
    "карточек товара для российских маркетплейсов (Ozon, Wildberries, Яндекс Маркет). "
    "По данным о товаре придумай план комплекта: какие слайды нужны, их роли, "
    "ключевые смыслы, акценты и тон. Опирайся на преимущества и целевую аудиторию. "
    "Первым слайдом всегда делай обложку (role=cover). Используй осмысленный порядок "
    "слайдов и не дублируй смыслы. Пиши на русском языке. "
    f"Рекомендованные роли слайдов: {', '.join(RECOMMENDED_ROLES)} — можешь выбрать "
    "подходящие или предложить свои. Верни строго структуру по заданной JSON-схеме."
)


def _format_brief(brief: ProductBrief) -> str:
    """Сериализовать бриф товара в читаемый для LLM текст."""
    lines = [f"Товар: {brief.title}"]
    if brief.brand_style:
        lines.append(f"Стиль бренда: {brief.brand_style}")
    if brief.target_audience:
        lines.append(f"Целевая аудитория: {brief.target_audience}")
    if brief.advantages:
        lines.append(f"Преимущества: {brief.advantages}")
    if brief.attributes:
        attrs = "; ".join(f"{k}: {v}" for k, v in brief.attributes.items())
        lines.append(f"Характеристики: {attrs}")
    if brief.requirements:
        reqs = "; ".join(f"{k}: {v}" for k, v in brief.requirements.items())
        lines.append(f"Требования к карточкам: {reqs}")
    return "\n".join(lines)


def build_ideas_request(
    brief: ProductBrief,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
) -> LLMRequest:
    """Собрать запрос к LLM для стадии [2]. Чистая функция — удобно тестировать."""
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=_format_brief(brief)),
        ],
        model=model,
        max_tokens=max_tokens,
        response_schema=IDEAS_RESPONSE_SCHEMA,
    )


async def generate_ideas(
    provider: LLMProvider,
    brief: ProductBrief,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
) -> tuple[ProductIdeas, LLMResponse]:
    """Сгенерировать идеи комплекта карточек.

    Возвращает валидированный :class:`ProductIdeas` и «сырой» :class:`LLMResponse`
    (для учёта стоимости/трейсинга — usage, модель, провайдер).
    """
    request = build_ideas_request(brief, model=model, max_tokens=max_tokens)
    response = await provider.complete(request)
    if response.data is None:
        raise ProviderError(
            "LLM не вернул структурированный ответ для стадии идей "
            f"(провайдер {response.provider!r}, модель {response.model!r})"
        )
    ideas = ProductIdeas.model_validate(response.data)
    return ideas, response

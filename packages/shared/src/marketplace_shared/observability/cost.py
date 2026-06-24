"""Оценка стоимости вызовов LLM/Image из :class:`Usage` (docs_marketplace/plan.md, Этап 5).

Когда провайдер сам не возвращает стоимость (``Usage.cost_usd is None``), оцениваем её
по ориентировочной ценовой таблице: для LLM — по токенам ввода/вывода, для image —
пер-изображение. Числа — приблизительные публичные цены на момент написания (2026) и
служат для учёта/наблюдаемости, а не для биллинга; правятся в одном месте — здесь.

Модуль чистый (без сети и без обращения к провайдерам): на вход — имя модели и метрики.
"""

from __future__ import annotations

from typing import Literal

from marketplace_shared.providers.contracts import Usage

#: Что за услуга — выбирает ценовую таблицу и способ расчёта.
ServiceKind = Literal["llm", "image"]

# --- Ценовые таблицы (ориентировочно, USD) --------------------------------- #
#: LLM: (цена за 1М входных токенов, цена за 1М выходных токенов).
_LLM_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
#: Дефолт для неизвестной LLM-модели (порядок величины Sonnet-класса).
_LLM_DEFAULT = (3.0, 15.0)

#: Image: цена за одно сгенерированное/отредактированное изображение.
_IMAGE_PRICING: dict[str, float] = {
    "gemini-2.5-flash-image": 0.039,
}
#: Дефолт для неизвестной image-модели.
_IMAGE_DEFAULT = 0.04

_MILLION = 1_000_000


def estimate_llm_cost(
    model: str | None, input_tokens: int | None, output_tokens: int | None
) -> float | None:
    """Оценить стоимость LLM-вызова в USD по токенам (None, если токенов нет)."""
    if not input_tokens and not output_tokens:
        return None
    in_price, out_price = _LLM_PRICING.get(model or "", _LLM_DEFAULT)
    cost = (input_tokens or 0) / _MILLION * in_price + (output_tokens or 0) / _MILLION * out_price
    return round(cost, 6)


def estimate_image_cost(model: str | None, images: int = 1) -> float | None:
    """Оценить стоимость image-вызова в USD (пер-изображение)."""
    if images <= 0:
        return None
    price = _IMAGE_PRICING.get(model or "", _IMAGE_DEFAULT)
    return round(price * images, 6)


def apply_estimated_cost(usage: Usage, *, kind: ServiceKind, model: str | None) -> Usage:
    """Вернуть копию ``usage`` с заполненным ``cost_usd``, если провайдер его не дал.

    Если стоимость уже известна (провайдер вернул) — отдаём как есть. Иначе оцениваем
    по таблице и помечаем в ``extra['cost_estimated'] = True`` (это оценка, не факт).
    """
    if usage.cost_usd is not None:
        return usage
    if kind == "llm":
        cost = estimate_llm_cost(model, usage.input_tokens, usage.output_tokens)
    else:
        images = int(usage.extra.get("images", 1)) if usage.extra else 1
        cost = estimate_image_cost(model, images)
    if cost is None:
        return usage
    return usage.model_copy(
        update={"cost_usd": cost, "extra": {**usage.extra, "cost_estimated": True}}
    )

"""Учёт стоимости генерации набора карточек (наблюдаемость, docs_marketplace/plan.md, Этап 5).

Эндпоинт ``GET /card-sets/{id}/cost`` агрегирует стоимость платных вызовов
image-генерации [5] по всем версиям набора (источник — ``CardVersion.gen_params_json
['usage']['cost_usd']``, заполняемый провайдером или оценкой
:mod:`marketplace_shared.observability.cost`). Прямо адресует риск «дорогая генерация»
из docs_marketplace/plan.md (раздел 8): менеджер видит накопленную стоимость комплекта.

Чистая агрегация (:func:`summarize_costs`) тестируема офлайн; роутер лишь читает БД.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import CardCost, CostSummary
from marketplace_shared.db import Card, CardSet, CardVersion, get_session

router = APIRouter(tags=["cost"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _version_cost(gen_params: dict[str, Any]) -> tuple[float, bool] | None:
    """Стоимость и признак «оценка» из gen_params версии (None, если платы нет)."""
    usage = gen_params.get("usage") or {}
    cost = usage.get("cost_usd")
    if cost is None:
        return None
    estimated = bool((usage.get("extra") or {}).get("cost_estimated"))
    return float(cost), estimated


def summarize_costs(
    card_set_id: uuid.UUID,
    cards: dict[uuid.UUID, Card],
    versions: Iterable[CardVersion],
) -> CostSummary:
    """Свести стоимость генераций [5] по версиям набора (чистая функция)."""
    per_card: dict[uuid.UUID, dict[str, Any]] = {}
    total = 0.0
    any_estimated = False
    total_gens = 0
    for version in versions:
        entry = _version_cost(version.gen_params_json or {})
        if entry is None:
            continue
        cost, estimated = entry
        total += cost
        total_gens += 1
        any_estimated = any_estimated or estimated
        bucket = per_card.setdefault(version.card_id, {"cost": 0.0, "gens": 0})
        bucket["cost"] += cost
        bucket["gens"] += 1

    by_card = [
        CardCost(
            card_id=card_id,
            role=cards[card_id].role if card_id in cards else "",
            order=cards[card_id].order if card_id in cards else 0,
            image_generations=data["gens"],
            cost_usd=round(data["cost"], 6),
        )
        for card_id, data in per_card.items()
    ]
    by_card.sort(key=lambda c: c.order)
    return CostSummary(
        card_set_id=card_set_id,
        total_cost_usd=round(total, 6),
        image_generations=total_gens,
        estimated=any_estimated,
        by_card=by_card,
    )


@router.get("/card-sets/{card_set_id}/cost", response_model=CostSummary)
async def card_set_cost(card_set_id: uuid.UUID, session: SessionDep) -> CostSummary:
    """Сводка стоимости генерации набора (404, если набора нет)."""
    card_set = await session.get(CardSet, card_set_id)
    if card_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Набор не найден")

    cards = {
        c.id: c
        for c in await session.scalars(select(Card).where(Card.card_set_id == card_set_id))
    }
    versions = list(
        await session.scalars(
            select(CardVersion)
            .join(Card, CardVersion.card_id == Card.id)
            .where(Card.card_set_id == card_set_id)
        )
    )
    return summarize_costs(card_set_id, cards, versions)

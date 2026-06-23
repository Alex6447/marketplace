"""Стадия [3] — визуальные концепции карточек (docs/plan.md, разделы 3 и 6).

Эндпоинты:
- ``POST /products/{id}/cards`` — сгенерировать концепции карточек (LLM) и сохранить
  их как набор карточек (``CardSet`` + ``Card`` с ``concept_json``);
- ``GET  /products/{id}/cards`` — получить последний сгенерированный набор.

Вход стадии — бриф товара + идеи комплекта (результат стадии [2], ``products.ideas_json``):
сначала нужно сгенерировать идеи. На Этапе 1 генерация выполняется синхронно в
обработчике запроса — без Celery; постановка в очередь и job/SSE (контракт ``→ job``
из раздела 6) появятся на Этапе 2. Логика стадии вынесена в
:mod:`marketplace_shared.pipeline.concepts` и от способа вызова не зависит.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import CardRead, CardSetRead, ConceptsGenerateRequest
from marketplace_shared.db import Card, CardSet, Product, Project, get_session
from marketplace_shared.pipeline import ProductBrief, ProductIdeas, generate_concepts
from marketplace_shared.providers import get_llm_provider
from marketplace_shared.providers.errors import ProviderError

router = APIRouter(tags=["cards"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _get_product_or_404(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    return product


async def _latest_card_set(session: AsyncSession, product_id: uuid.UUID) -> CardSet | None:
    """Последний набор карточек товара (по времени создания)."""
    return await session.scalar(
        select(CardSet)
        .where(CardSet.product_id == product_id)
        .order_by(CardSet.created_at.desc())
        .limit(1)
    )


async def _cards_of_set(session: AsyncSession, card_set_id: uuid.UUID) -> list[Card]:
    result = await session.scalars(
        select(Card).where(Card.card_set_id == card_set_id).order_by(Card.order)
    )
    return list(result.all())


@router.post(
    "/products/{product_id}/cards",
    response_model=CardSetRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_product_cards(
    product_id: uuid.UUID, payload: ConceptsGenerateRequest, session: SessionDep
) -> CardSetRead:
    """Сгенерировать визуальные концепции карточек для товара.

    Требует ранее сгенерированных идей (стадия [2]). Идемпотентность: если набор уже
    есть и ``force`` не задан — 409; с ``force=true`` прежние наборы товара удаляются
    и концепции генерируются заново.
    """
    product = await _get_product_or_404(session, product_id)
    if product.ideas_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сначала сгенерируйте идеи (стадия [2]) для этого товара",
        )

    existing = await _latest_card_set(session, product_id)
    if existing is not None and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Концепции для товара уже сгенерированы; передайте force=true для перегенерации",
        )

    # Вход стадии [3]: бриф товара (+ стиль бренда из проекта) и идеи комплекта.
    project = await session.get(Project, product.project_id)
    brief = ProductBrief(
        title=product.title,
        attributes=product.attributes_json,
        advantages=product.advantages,
        target_audience=product.target_audience,
        requirements=product.requirements_json,
        brand_style=project.brand_style if project is not None else None,
    )
    ideas = ProductIdeas.model_validate(product.ideas_json)

    provider = get_llm_provider()
    try:
        concepts, _response = await generate_concepts(
            provider, brief, ideas, model=payload.model
        )
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка генерации концепций: {exc}",
        ) from exc

    # force: убираем прежние наборы товара (каскад удалит их карточки).
    if existing is not None:
        old_sets = await session.scalars(
            select(CardSet).where(CardSet.product_id == product_id)
        )
        for old in old_sets.all():
            await session.delete(old)

    card_set = CardSet(
        project_id=product.project_id,
        product_id=product.id,
        status="ready",
    )
    session.add(card_set)
    await session.flush()  # нужен card_set.id для карточек

    cards = [
        Card(
            card_set_id=card_set.id,
            role=concept.role,
            concept_json=concept.model_dump(),
            order=index,
        )
        for index, concept in enumerate(concepts.cards)
    ]
    session.add_all(cards)
    await session.commit()

    return CardSetRead(
        id=card_set.id,
        product_id=product.id,
        status=card_set.status,
        cards=[CardRead.model_validate(card) for card in cards],
    )


@router.get("/products/{product_id}/cards", response_model=CardSetRead)
async def get_product_cards(product_id: uuid.UUID, session: SessionDep) -> CardSetRead:
    """Получить последний набор карточек товара (404, если товара нет или нет набора)."""
    product = await _get_product_or_404(session, product_id)
    card_set = await _latest_card_set(session, product_id)
    if card_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Концепции карточек для товара ещё не сгенерированы",
        )
    cards = await _cards_of_set(session, card_set.id)
    return CardSetRead(
        id=card_set.id,
        product_id=product.id,
        status=card_set.status,
        cards=[CardRead.model_validate(card) for card in cards],
    )

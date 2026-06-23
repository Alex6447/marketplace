"""Стадия [2] — генерация идей карточек (docs/plan.md, разделы 3 и 6).

Эндпоинты:
- ``POST /products/{id}/ideas`` — запустить генерацию идей (LLM) и сохранить результат;
- ``GET  /products/{id}/ideas`` — получить ранее сгенерированные идеи.

На Этапе 1 (текстовый пайплайн без картинок) генерация выполняется синхронно в
обработчике запроса — без Celery. Постановка стадии в очередь и job/SSE-прогресс
(контракт ``→ job`` из раздела 6) появятся на Этапе 2; логика самой стадии вынесена
в :mod:`marketplace_shared.pipeline.ideas` и от способа вызова не зависит.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import IdeasGenerateRequest, IdeasRead
from marketplace_shared.db import Product, Project, get_session
from marketplace_shared.pipeline import ProductBrief, generate_ideas
from marketplace_shared.providers import get_llm_provider
from marketplace_shared.providers.errors import ProviderError

router = APIRouter(tags=["ideas"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _get_product_or_404(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    return product


@router.post(
    "/products/{product_id}/ideas",
    response_model=IdeasRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_product_ideas(
    product_id: uuid.UUID, payload: IdeasGenerateRequest, session: SessionDep
) -> IdeasRead:
    """Сгенерировать идеи комплекта карточек для товара.

    Идемпотентность: если идеи уже есть и ``force`` не задан — 409 (повторный запуск
    перетёр бы результат). С ``force=true`` идеи перегенерируются и заменяются.
    """
    product = await _get_product_or_404(session, product_id)
    if product.ideas_json is not None and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Идеи для товара уже сгенерированы; передайте force=true для перегенерации",
        )

    # Стиль бренда — из проекта (вход стадии идей).
    project = await session.get(Project, product.project_id)
    brief = ProductBrief(
        title=product.title,
        attributes=product.attributes_json,
        advantages=product.advantages,
        target_audience=product.target_audience,
        requirements=product.requirements_json,
        brand_style=project.brand_style if project is not None else None,
    )

    provider = get_llm_provider()
    try:
        ideas, _response = await generate_ideas(provider, brief, model=payload.model)
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка генерации идей: {exc}",
        ) from exc

    product.ideas_json = ideas.model_dump()
    await session.commit()
    return IdeasRead(product_id=product.id, ideas=product.ideas_json)


@router.get("/products/{product_id}/ideas", response_model=IdeasRead)
async def get_product_ideas(product_id: uuid.UUID, session: SessionDep) -> IdeasRead:
    """Получить сохранённые идеи товара (404, если товара нет или идеи не сгенерированы)."""
    product = await _get_product_or_404(session, product_id)
    if product.ideas_json is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Идеи для товара ещё не сгенерированы",
        )
    return IdeasRead(product_id=product.id, ideas=product.ideas_json)

"""CRUD-роутер товаров (docs_marketplace/plan.md, раздел 6).

Товар принадлежит проекту. Создание товара — это ввод описания/характеристик;
загрузка фото и референсов вынесена в роутер `assets`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import ProductCreate, ProductRead
from marketplace_shared.db import Product, Project, get_session

router = APIRouter(tags=["products"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post(
    "/projects/{project_id}/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    project_id: uuid.UUID, payload: ProductCreate, session: SessionDep
) -> Product:
    """Создать товар в проекте (404, если проекта нет)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    product = Product(
        project_id=project_id,
        title=payload.title,
        attributes_json=payload.attributes_json,
        advantages=payload.advantages,
        target_audience=payload.target_audience,
        requirements_json=payload.requirements_json,
    )
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.get("/projects/{project_id}/products", response_model=list[ProductRead])
async def list_products(project_id: uuid.UUID, session: SessionDep) -> list[Product]:
    """Список товаров проекта (404, если проекта нет)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")

    result = await session.scalars(
        select(Product).where(Product.project_id == project_id).order_by(Product.title)
    )
    return list(result.all())


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(product_id: uuid.UUID, session: SessionDep) -> Product:
    """Получить товар по id (404, если не найден)."""
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    return product

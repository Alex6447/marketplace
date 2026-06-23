"""Стадия [5] — генерация изображения карточки (docs/plan.md, разделы 3, 4 и 6).

Эндпоинты ставят задачу в очередь и сразу возвращают :class:`Job` (202); тяжёлую
работу делает worker (стадии в :mod:`marketplace_worker.stages`). Прогресс — через
``GET /jobs/{id}`` и SSE ``GET /jobs/{id}/events``.

- ``POST /cards/{id}/generate`` — одна карточка (режим edit/composite);
- ``POST /card-sets/{id}/generate`` — весь набор: Celery `chord(group(...), finalize)`,
  при ``prepare=true`` каждая карточка — `chain(matting, composite)`;
- ``GET  /cards/{id}/versions`` — версии карточки (результаты стадии [5]).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.enqueue import enqueue_card_image, enqueue_card_set
from marketplace_api.schemas import (
    CardImageGenerateRequest,
    CardSetGenerateRequest,
    CardVersionRead,
    JobRead,
)
from marketplace_shared import jobs as job_const
from marketplace_shared.db import (
    Card,
    CardSet,
    CardVersion,
    Job,
    ProductAsset,
    get_session,
)
from marketplace_shared.storage import S3Storage, get_storage

router = APIRouter(tags=["generate"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[S3Storage, Depends(get_storage)]


async def _get_card_or_404(session: AsyncSession, card_id: uuid.UUID) -> Card:
    card = await session.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена")
    return card


async def _photo_asset(session: AsyncSession, product_id: uuid.UUID) -> ProductAsset | None:
    return await session.scalar(
        select(ProductAsset)
        .where(ProductAsset.product_id == product_id, ProductAsset.type == "photo")
        .order_by(ProductAsset.id)
        .limit(1)
    )


def _with_url(version: CardVersion, storage: S3Storage) -> CardVersionRead:
    """DTO версии с presigned-ссылкой на изображение (если оно есть)."""
    dto = CardVersionRead.model_validate(version)
    if version.image_s3_key:
        dto.image_url = storage.presigned_get_url(version.image_s3_key)
    return dto


@router.post(
    "/cards/{card_id}/generate",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_card_version(
    card_id: uuid.UUID, payload: CardImageGenerateRequest, session: SessionDep
) -> JobRead:
    """Поставить генерацию изображения карточки в очередь (стадия [5]).

    Быстрая валидация (наличие концепции) — синхронно; сама генерация уходит в worker.
    Возвращает задачу (Job); прогресс — через ``/jobs/{id}`` и SSE.
    """
    card = await _get_card_or_404(session, card_id)
    if card.concept_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У карточки нет концепции (стадия [3]); сначала сгенерируйте концепции",
        )

    job = Job(
        type=job_const.JOB_CARD_IMAGE,
        status=job_const.JOB_PENDING,
        payload_json={
            "card_id": str(card_id),
            "mode": payload.mode,
            "model": payload.model,
            "seed": payload.seed,
            "size": payload.size,
            "use_references": payload.use_references,
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    enqueue_card_image(
        job.id,
        card_id,
        mode=payload.mode,
        model=payload.model,
        seed=payload.seed,
        size=payload.size,
        use_references=payload.use_references,
    )
    return JobRead.model_validate(job)


@router.post(
    "/card-sets/{card_set_id}/generate",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_card_set_images(
    card_set_id: uuid.UUID, payload: CardSetGenerateRequest, session: SessionDep
) -> JobRead:
    """Поставить генерацию изображений всего набора карточек (стадия [5]).

    Под капотом — Celery `chord(group(card_image…), finalize)`; при ``prepare=true``
    каждая карточка идёт цепочкой `chain(matting, composite)`. Создаёт родительскую
    задачу набора и по дочерней задаче на карточку (и на matting при ``prepare``).
    """
    card_set = await session.get(CardSet, card_set_id)
    if card_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Набор не найден")

    cards = list(
        await session.scalars(
            select(Card).where(Card.card_set_id == card_set_id).order_by(Card.order)
        )
    )
    if not cards:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="В наборе нет карточек"
        )

    # Для prepare/композитинга нужна привязка к товару и его фото.
    asset_id: uuid.UUID | None = None
    if payload.prepare:
        if card_set.product_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Набор не привязан к товару — нет фото для подготовки маски",
            )
        photo = await _photo_asset(session, card_set.product_id)
        if photo is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="У товара нет фото (type=photo) для подготовки маски",
            )
        asset_id = photo.id

    parent = Job(
        type=job_const.JOB_CARD_SET_IMAGES,
        status=job_const.JOB_PENDING,
        payload_json={
            "card_set_id": str(card_set_id),
            "mode": payload.mode,
            "prepare": payload.prepare,
        },
    )
    session.add(parent)

    items: list[dict] = []
    for card in cards:
        image_job = Job(
            type=job_const.JOB_CARD_IMAGE,
            status=job_const.JOB_PENDING,
            payload_json={"card_id": str(card.id), "mode": payload.mode},
        )
        session.add(image_job)
        await session.flush()  # нужен image_job.id
        item: dict = {
            "image_job_id": str(image_job.id),
            "card_id": str(card.id),
            "mode": payload.mode,
            "model": payload.model,
            "seed": payload.seed,
            "size": payload.size,
            "use_references": payload.use_references,
        }
        if payload.prepare:
            matting_job = Job(
                type=job_const.JOB_ASSET_MATTING,
                status=job_const.JOB_PENDING,
                payload_json={"asset_id": str(asset_id)},
            )
            session.add(matting_job)
            await session.flush()
            item["matting_job_id"] = str(matting_job.id)
            item["asset_id"] = str(asset_id)
        items.append(item)

    await session.commit()
    await session.refresh(parent)

    enqueue_card_set(parent.id, items, prepare=payload.prepare)
    return JobRead.model_validate(parent)


@router.get("/cards/{card_id}/versions", response_model=list[CardVersionRead])
async def list_card_versions(
    card_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> list[CardVersionRead]:
    """Версии карточки с presigned-ссылками (404, если карточки нет)."""
    await _get_card_or_404(session, card_id)
    result = await session.scalars(
        select(CardVersion)
        .where(CardVersion.card_id == card_id)
        .order_by(CardVersion.version_no)
    )
    versions = list(result.all())
    return await run_in_threadpool(lambda: [_with_url(v, storage) for v in versions])

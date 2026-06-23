"""Стадия [5] — генерация изображения карточки (docs/plan.md, разделы 3, 4 и 6).

Эндпоинты:
- ``POST /cards/{id}/generate`` — основной режим стадии [5]: editing-модель через
  :class:`ImageProvider` («оставь товар, измени фон/сцену») создаёт новую версию
  карточки (``CardVersion`` с ``image_s3_key``);
- ``GET  /cards/{id}/versions`` — версии карточки с presigned-ссылками.

Вход стадии: визуальная концепция карточки (``Card.concept_json``, результат стадии
[3]) + реальное фото товара (``ProductAsset`` типа ``photo``). Фото читается из MinIO
и передаётся провайдеру inline-байтами; результат сохраняется обратно в MinIO.

На Этапе 2 (этот этап) генерация выполняется синхронно в обработчике — постановка в
очередь Celery и SSE-прогресс (контракт ``→ job`` из раздела 6) появятся отдельным
пунктом этапа. Логика самой стадии вынесена в
:mod:`marketplace_shared.pipeline.imagegen` и от способа вызова не зависит.
"""

from __future__ import annotations

import mimetypes
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import CardImageGenerateRequest, CardVersionRead
from marketplace_shared.db import (
    Card,
    CardSet,
    CardVersion,
    Product,
    ProductAsset,
    Project,
    get_session,
)
from marketplace_shared.pipeline import CardConcept, generate_card_image
from marketplace_shared.providers import ImageRef, get_image_provider
from marketplace_shared.providers.errors import ProviderError, ProviderNotConfigured
from marketplace_shared.storage import S3Storage, get_storage

router = APIRouter(tags=["generate"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[S3Storage, Depends(get_storage)]


async def _get_card_or_404(session: AsyncSession, card_id: uuid.UUID) -> Card:
    card = await session.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена")
    return card


def _media_type_for(key: str) -> str:
    """Определить MIME изображения по расширению ключа (по умолчанию image/png)."""
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "image/png"


def _ref_from_storage(storage: S3Storage, key: str) -> ImageRef:
    """Прочитать объект из хранилища и собрать inline-:class:`ImageRef`."""
    data = storage.get_object(key)
    return ImageRef(data=data, media_type=_media_type_for(key))


def _with_url(version: CardVersion, storage: S3Storage) -> CardVersionRead:
    """DTO версии с presigned-ссылкой на изображение (если оно есть)."""
    dto = CardVersionRead.model_validate(version)
    if version.image_s3_key:
        dto.image_url = storage.presigned_get_url(version.image_s3_key)
    return dto


@router.post(
    "/cards/{card_id}/generate",
    response_model=CardVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_card_version(
    card_id: uuid.UUID,
    payload: CardImageGenerateRequest,
    session: SessionDep,
    storage: StorageDep,
) -> CardVersionRead:
    """Сгенерировать изображение карточки (основной режим стадии [5]).

    Требует визуальную концепцию (стадия [3]) и хотя бы одно фото товара. Каждый
    вызов создаёт новую версию карточки (история версий копится).
    """
    card = await _get_card_or_404(session, card_id)
    if card.concept_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У карточки нет концепции (стадия [3]); сначала сгенерируйте концепции",
        )

    card_set = await session.get(CardSet, card.card_set_id)
    if card_set is None or card_set.product_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Набор карточек не привязан к товару — неоткуда взять фото товара",
        )
    product = await session.get(Product, card_set.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Товар набора не найден",
        )

    # Фото товара — его и нужно сохранить без искажений (вход стадии [5]).
    photo = await session.scalar(
        select(ProductAsset)
        .where(ProductAsset.product_id == product.id, ProductAsset.type == "photo")
        .order_by(ProductAsset.id)
        .limit(1)
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У товара нет фото (ProductAsset type=photo) для генерации",
        )

    reference_keys: list[str] = []
    if payload.use_references:
        refs = await session.scalars(
            select(ProductAsset)
            .where(ProductAsset.product_id == product.id, ProductAsset.type == "reference")
            .order_by(ProductAsset.id)
        )
        reference_keys = [asset.s3_key for asset in refs.all()]

    project = await session.get(Project, product.project_id)
    concept = CardConcept.model_validate(card.concept_json)

    # Читаем фото и референсы из хранилища (boto3 синхронный → threadpool).
    product_photo = await run_in_threadpool(_ref_from_storage, storage, photo.s3_key)
    references = [
        await run_in_threadpool(_ref_from_storage, storage, key) for key in reference_keys
    ]

    try:
        provider = get_image_provider()
        result, instruction = await generate_card_image(
            provider,
            product_photo=product_photo,
            concept=concept,
            references=references,
            brand_style=project.brand_style if project is not None else None,
            model=payload.model,
            size=payload.size,
            seed=payload.seed,
        )
    except ProviderNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Image-провайдер не сконфигурирован: {exc}",
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка генерации изображения: {exc}",
        ) from exc

    if result.image.data is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Image-провайдер не вернул байты изображения",
        )

    # Следующий номер версии (история версий карточки).
    last_no = await session.scalar(
        select(func.max(CardVersion.version_no)).where(CardVersion.card_id == card.id)
    )
    version_no = (last_no or 0) + 1

    version_id = uuid.uuid4()
    extension = mimetypes.guess_extension(result.image.media_type) or ".png"
    key = f"cards/{card.id}/versions/{version_id}{extension}"
    await run_in_threadpool(
        storage.put_object, key, result.image.data, result.image.media_type
    )

    version = CardVersion(
        id=version_id,
        card_id=card.id,
        version_no=version_no,
        image_s3_key=key,
        gen_params_json={
            "stage": "image_edit",
            "provider": result.provider,
            "model": result.model,
            "seed": payload.seed,
            "instruction": instruction,
            "usage": result.usage.model_dump(),
        },
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)

    return await run_in_threadpool(_with_url, version, storage)


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

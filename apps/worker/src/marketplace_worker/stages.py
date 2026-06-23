"""Синхронная оркестрация стадий пайплайна в воркере (docs/plan.md, раздел 3).

Здесь — «клей» между провайдеро-независимой логикой стадий (:mod:`marketplace_shared.
pipeline`), хранилищем (MinIO/S3) и БД, исполняемый синхронно в Celery-задачах. Сами
провайдеры асинхронные — оборачиваем их в :func:`_run` (`asyncio.run`). Стадии [4] и
[5] перенесены сюда из синхронных API-роутеров Этапа 1: теперь API лишь ставит задачу.

- :func:`run_asset_matting` — стадия [4]: удаление фона + маска/вырез товара.
- :func:`run_card_image` — стадия [5]: editing или композитинг → новая версия карточки.
"""

from __future__ import annotations

import asyncio
import mimetypes
import sys
import uuid
from collections.abc import Coroutine
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marketplace_shared.db import (
    Card,
    CardSet,
    CardVersion,
    Product,
    ProductAsset,
    Project,
)
from marketplace_shared.pipeline import (
    CardConcept,
    composite_product_on_background,
    generate_card_background,
    generate_card_image,
    prepare_asset,
)
from marketplace_shared.providers import (
    ImageRef,
    get_image_provider,
    get_matting_provider,
)
from marketplace_shared.storage import get_storage


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Выполнить async-вызов провайдера из синхронной задачи.

    На Windows async-psycopg несовместим с ProactorEventLoop; провайдеры psycopg не
    используют, но политика безопасна и для них. Каждая задача — свой event loop.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


def _media_type_for(key: str) -> str:
    guessed, _ = mimetypes.guess_type(key)
    return guessed or "image/png"


def _mask_key(product_id: uuid.UUID, asset_id: uuid.UUID) -> str:
    return f"products/{product_id}/assets/{asset_id}.mask.png"


def _cutout_key(mask_key: str) -> str:
    return mask_key.removesuffix(".mask.png") + ".cutout.png"


def _materialize(ref: ImageRef) -> bytes:
    """Байты изображения: inline-данные или скачивание по presigned-URL (sync)."""
    if ref.data is not None:
        return ref.data
    with httpx.Client(timeout=60.0) as client:
        response = client.get(ref.url)  # type: ignore[arg-type]  # url задан (валидатор ImageRef)
        response.raise_for_status()
    return response.content


# --------------------------------------------------------------------------- #
# Стадия [4] — удаление фона / маска
# --------------------------------------------------------------------------- #


def run_asset_matting(
    session: Session, asset_id: uuid.UUID, *, model: str | None = None
) -> dict[str, Any]:
    """Построить маску и вырез товара, сохранить в хранилище, проставить mask_s3_key."""
    asset = session.get(ProductAsset, asset_id)
    if asset is None:
        raise ValueError("Ассет не найден")
    if asset.type != "photo":
        raise ValueError("Маска строится только для фото товара (type=photo)")

    storage = get_storage()
    photo_bytes = storage.get_object(asset.s3_key)
    provider = get_matting_provider()
    image = ImageRef(data=photo_bytes, media_type=_media_type_for(asset.s3_key))
    result = _run(prepare_asset(provider, image, model=model))

    mask_key = _mask_key(asset.product_id, asset.id)
    storage.put_object(mask_key, result.mask.data, "image/png")
    if result.cutout is not None and result.cutout.data is not None:
        storage.put_object(_cutout_key(mask_key), result.cutout.data, "image/png")

    asset.mask_s3_key = mask_key
    session.commit()
    return {"asset_id": str(asset.id), "mask_s3_key": mask_key, "provider": result.provider}


# --------------------------------------------------------------------------- #
# Стадия [5] — генерация изображения карточки
# --------------------------------------------------------------------------- #


def run_card_image(
    session: Session,
    card_id: uuid.UUID,
    *,
    mode: str = "edit",
    model: str | None = None,
    seed: int | None = None,
    size: str | None = None,
    use_references: bool = True,
) -> dict[str, Any]:
    """Сгенерировать изображение карточки (edit/composite) и создать новую версию."""
    card = session.get(Card, card_id)
    if card is None:
        raise ValueError("Карточка не найдена")
    if card.concept_json is None:
        raise ValueError("У карточки нет концепции (стадия [3])")

    card_set = session.get(CardSet, card.card_set_id)
    if card_set is None or card_set.product_id is None:
        raise ValueError("Набор карточек не привязан к товару")
    product = session.get(Product, card_set.product_id)
    if product is None:
        raise ValueError("Товар набора не найден")

    photo = session.scalar(
        select(ProductAsset)
        .where(ProductAsset.product_id == product.id, ProductAsset.type == "photo")
        .order_by(ProductAsset.id)
        .limit(1)
    )
    if photo is None:
        raise ValueError("У товара нет фото (type=photo) для генерации")

    storage = get_storage()
    references: list[ImageRef] = []
    if use_references:
        refs = session.scalars(
            select(ProductAsset)
            .where(ProductAsset.product_id == product.id, ProductAsset.type == "reference")
            .order_by(ProductAsset.id)
        )
        references = [
            ImageRef(data=storage.get_object(a.s3_key), media_type=_media_type_for(a.s3_key))
            for a in refs.all()
        ]

    project = session.get(Project, product.project_id)
    brand_style = project.brand_style if project is not None else None
    concept = CardConcept.model_validate(card.concept_json)
    provider = get_image_provider()

    if mode == "composite":
        if not photo.mask_s3_key:
            raise ValueError("Для композитинга нужна маска товара — сначала стадия [4]")
        cutout = storage.get_object(_cutout_key(photo.mask_s3_key))
        result, prompt = _run(
            generate_card_background(
                provider,
                concept,
                references=references,
                brand_style=brand_style,
                model=model,
                size=size,
                seed=seed,
            )
        )
        image_bytes = composite_product_on_background(_materialize(result.image), cutout)
        gen_params: dict[str, Any] = {
            "stage": "image_composite",
            "mode": "composite",
            "provider": result.provider,
            "model": result.model,
            "seed": seed,
            "background_prompt": prompt,
            "usage": result.usage.model_dump(),
        }
    else:
        product_photo = ImageRef(
            data=storage.get_object(photo.s3_key), media_type=_media_type_for(photo.s3_key)
        )
        result, instruction = _run(
            generate_card_image(
                provider,
                product_photo=product_photo,
                concept=concept,
                references=references,
                brand_style=brand_style,
                model=model,
                size=size,
                seed=seed,
            )
        )
        image_bytes = _materialize(result.image)
        gen_params = {
            "stage": "image_edit",
            "mode": "edit",
            "provider": result.provider,
            "model": result.model,
            "seed": seed,
            "instruction": instruction,
            "usage": result.usage.model_dump(),
        }

    last_no = session.scalar(
        select(func.max(CardVersion.version_no)).where(CardVersion.card_id == card.id)
    )
    version_no = (last_no or 0) + 1
    version_id = uuid.uuid4()
    key = f"cards/{card.id}/versions/{version_id}.png"
    storage.put_object(key, image_bytes, "image/png")

    version = CardVersion(
        id=version_id,
        card_id=card.id,
        version_no=version_no,
        image_s3_key=key,
        gen_params_json=gen_params,
    )
    session.add(version)
    session.commit()
    return {
        "card_id": str(card.id),
        "card_version_id": str(version_id),
        "version_no": version_no,
        "image_s3_key": key,
        "mode": mode,
    }

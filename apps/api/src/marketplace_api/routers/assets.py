"""Роутер ассетов товара: загрузка фото/референсов в MinIO (docs/plan.md, раздел 6).

Файл кладётся в S3-хранилище по ключу `products/{product_id}/assets/{asset_id}<ext>`,
а в БД сохраняется запись `ProductAsset` со ссылкой на ключ. Само изображение в БД
не хранится. В ответе отдаётся presigned-URL для скачивания.

Вызовы boto3 синхронные — оборачиваем в threadpool, чтобы не блокировать
async event loop FastAPI.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.enqueue import enqueue_asset_matting
from marketplace_api.schemas import AssetType, JobRead, MaskGenerateRequest, ProductAssetRead
from marketplace_shared import jobs as job_const
from marketplace_shared.db import Job, Product, ProductAsset, get_session
from marketplace_shared.storage import S3Storage, get_storage

router = APIRouter(prefix="/products/{product_id}/assets", tags=["assets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[S3Storage, Depends(get_storage)]

#: Ограничение размера загружаемого фото (20 МБ) — отсев случайных гигантских файлов.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _object_key(product_id: uuid.UUID, asset_id: uuid.UUID, filename: str | None) -> str:
    """Сформировать ключ объекта в бакете, сохранив расширение исходного файла."""
    suffix = PurePosixPath(filename).suffix if filename else ""
    return f"products/{product_id}/assets/{asset_id}{suffix}"


def _cutout_key(mask_key: str) -> str:
    """Ключ выреза с прозрачным фоном — сосед маски по имени (стадия [4])."""
    return mask_key.removesuffix(".mask.png") + ".cutout.png"


def _with_url(asset: ProductAsset, storage: S3Storage) -> ProductAssetRead:
    """Собрать DTO ассета с presigned-URL (само фото + маска/вырез, если есть)."""
    dto = ProductAssetRead.model_validate(asset)
    dto.url = storage.presigned_get_url(asset.s3_key)
    if asset.mask_s3_key:
        dto.mask_url = storage.presigned_get_url(asset.mask_s3_key)
        dto.cutout_url = storage.presigned_get_url(_cutout_key(asset.mask_s3_key))
    return dto


@router.post("", response_model=ProductAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    product_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File(description="Фото товара или референс")],
    type: Annotated[AssetType, Form(description="photo | reference")] = "photo",
) -> ProductAssetRead:
    """Загрузить фото/референс товара в хранилище и зарегистрировать ассет."""
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Файл превышает 20 МБ",
        )

    asset_id = uuid.uuid4()
    key = _object_key(product_id, asset_id, file.filename)
    await run_in_threadpool(storage.put_object, key, data, file.content_type)

    asset = ProductAsset(id=asset_id, product_id=product_id, type=type, s3_key=key)
    session.add(asset)
    await session.commit()
    await session.refresh(asset)

    return await run_in_threadpool(_with_url, asset, storage)


@router.get("", response_model=list[ProductAssetRead])
async def list_assets(
    product_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> list[ProductAssetRead]:
    """Список ассетов товара с presigned-URL на скачивание (404, если товара нет)."""
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")

    result = await session.scalars(
        select(ProductAsset)
        .where(ProductAsset.product_id == product_id)
        .order_by(ProductAsset.type)
    )
    assets = list(result.all())
    return await run_in_threadpool(lambda: [_with_url(a, storage) for a in assets])


@router.post(
    "/{asset_id}/mask", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED
)
async def generate_asset_mask(
    product_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: MaskGenerateRequest,
    session: SessionDep,
) -> JobRead:
    """Поставить удаление фона и построение маски товара в очередь (стадия [4]).

    Только для фото (``type=photo``). Идемпотентность: если маска уже есть и ``force``
    не задан — 409. Сам matting выполняет worker; результат пишется в
    ``ProductAsset.mask_s3_key``. Возвращает задачу (Job).
    """
    asset = await session.get(ProductAsset, asset_id)
    if asset is None or asset.product_id != product_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ассет не найден")
    if asset.type != "photo":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Маска строится только для фото товара (type=photo)",
        )
    if asset.mask_s3_key and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Маска уже построена; передайте force=true для пересборки",
        )

    job = Job(
        type=job_const.JOB_ASSET_MATTING,
        status=job_const.JOB_PENDING,
        payload_json={"asset_id": str(asset_id), "model": payload.model},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    enqueue_asset_matting(job.id, asset_id, model=payload.model)
    return JobRead.model_validate(job)

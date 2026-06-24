"""Стадия [7] — автоматические QA-проверки версии карточки (docs/plan.md, разделы 3 и 6).

Эндпоинты:
- ``POST /card-versions/{id}/qa`` — прогнать проверки и сохранить отчёт;
- ``GET  /card-versions/{id}/qa`` — последний сохранённый отчёт.

QA — лёгкая локальная стадия (Pillow, без сети и без провайдеров), поэтому выполняется
синхронно в обработчике, как разбор фидбэка [9] (а не через очередь, как тяжёлые [4]/[5]/
[6]). Чистая логика проверок — в :mod:`marketplace_shared.pipeline.qa`; здесь только сбор
байтов из хранилища и запись отчёта в ``CardVersion.qa_report_json``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import QaRunRequest
from marketplace_shared.db import Card, CardSet, CardVersion, ProductAsset, get_session
from marketplace_shared.pipeline import CardConcept, QaReport, build_qa_report
from marketplace_shared.storage import S3Storage, get_storage
from marketplace_shared.textrender import get_template

router = APIRouter(tags=["qa"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[S3Storage, Depends(get_storage)]


async def _get_version_or_404(session: AsyncSession, version_id: uuid.UUID) -> CardVersion:
    version = await session.get(CardVersion, version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Версия карточки не найдена"
        )
    return version


async def _photo_asset(session: AsyncSession, product_id: uuid.UUID) -> ProductAsset | None:
    return await session.scalar(
        select(ProductAsset)
        .where(ProductAsset.product_id == product_id, ProductAsset.type == "photo")
        .order_by(ProductAsset.id)
        .limit(1)
    )


def _build_report_sync(
    *,
    storage: S3Storage,
    concept: CardConcept | None,
    template_key: str,
    final_key: str | None,
    image_key: str | None,
    source_key: str | None,
    mask_key: str | None,
    mode: str | None,
) -> QaReport:
    """Загрузить байты из хранилища и собрать отчёт (синхронно, для threadpool)."""
    template = get_template(template_key)
    final_png = storage.get_object(final_key) if final_key else None
    image_png = storage.get_object(image_key) if image_key else None
    source_png = storage.get_object(source_key) if source_key else None
    mask_png = storage.get_object(mask_key) if mask_key else None
    return build_qa_report(
        concept=concept,
        template=template,
        final_png=final_png,
        image_png=image_png,
        source_png=source_png,
        mask_png=mask_png,
        mode=mode,
    )


@router.post("/card-versions/{version_id}/qa", response_model=QaReport)
async def run_qa(
    version_id: uuid.UUID,
    payload: QaRunRequest,
    session: SessionDep,
    storage: StorageDep,
) -> QaReport:
    """Прогнать авто-QA версии карточки и сохранить отчёт (стадия [7]).

    Проверяет размеры/соотношение под МП, читаемость текста, сохранность товара
    (по маске [4], если есть) и белый фон главной карточки. Требует хотя бы одного
    изображения у версии (стадия [5] или [6]).
    """
    version = await _get_version_or_404(session, version_id)
    if not version.image_s3_key and not version.final_s3_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У версии нет изображения (стадии [5]/[6]) — нечего проверять",
        )

    # Концепция карточки [3] — для текстовых проверок и запрещённых элементов.
    concept: CardConcept | None = None
    source_key: str | None = None
    mask_key: str | None = None
    card = await session.get(Card, version.card_id)
    if card is not None:
        if card.concept_json is not None:
            concept = CardConcept.model_validate(card.concept_json)
        card_set = await session.get(CardSet, card.card_set_id)
        if card_set is not None and card_set.product_id is not None:
            photo = await _photo_asset(session, card_set.product_id)
            if photo is not None:
                source_key = photo.s3_key
                mask_key = photo.mask_s3_key

    # Шаблон: из запроса → из стадии [6] версии → дефолтный.
    overlay = version.gen_params_json.get("text_overlay") or {}
    template_key = payload.template_key or overlay.get("template")
    mode = version.gen_params_json.get("mode")

    try:
        report = await run_in_threadpool(
            _build_report_sync,
            storage=storage,
            concept=concept,
            template_key=template_key,
            final_key=version.final_s3_key,
            image_key=version.image_s3_key,
            source_key=source_key,
            mask_key=mask_key,
            mode=mode,
        )
    except KeyError as exc:  # неизвестный template_key
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    version.qa_report_json = report.model_dump(mode="json")
    await session.commit()
    return report


@router.get("/card-versions/{version_id}/qa", response_model=QaReport)
async def get_qa(version_id: uuid.UUID, session: SessionDep) -> QaReport:
    """Последний сохранённый отчёт авто-QA версии (404, если проверка не запускалась)."""
    version = await _get_version_or_404(session, version_id)
    if not version.qa_report_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="QA для версии ещё не запускалось"
        )
    return QaReport.model_validate(version.qa_report_json)

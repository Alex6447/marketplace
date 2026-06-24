"""Стадия [9] — разбор свободного фидбэка менеджера (docs/plan.md, разделы 3 и 6).

Эндпоинты:
- ``POST /card-versions/{id}/feedback`` — принять текст фидбэка, разобрать его LLM
  (действие + целевая стадия + дельта-параметры) и сохранить;
- ``GET  /card-versions/{id}/feedback`` — история фидбэка к версии карточки.

Разбор — лёгкая LLM-стадия: как идеи [2] и концепции [3], выполняется синхронно в
обработчике (без Celery). Перегенерация адресуемой стадии по разобранному действию —
следующий пункт Этапа 4 (она уйдёт в очередь). Логика парсинга вынесена в
:mod:`marketplace_shared.pipeline.feedback` и от способа вызова не зависит.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.enqueue import enqueue_feedback_regen
from marketplace_api.schemas import (
    FeedbackCreate,
    FeedbackRead,
    FeedbackRegenerateRequest,
    JobRead,
)
from marketplace_shared import jobs as job_const
from marketplace_shared.db import (
    Card,
    CardSet,
    CardVersion,
    Feedback,
    Job,
    Project,
    get_session,
)
from marketplace_shared.pipeline import CardConcept, FeedbackInput, parse_feedback
from marketplace_shared.providers import get_llm_provider
from marketplace_shared.providers.errors import ProviderError

#: Стадии, которые перегенерируются автоматически по фидбэку (остальные — вручную).
_AUTO_REGEN_STAGES = frozenset({"concept", "image", "text"})

router = APIRouter(tags=["feedback"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _get_version_or_404(session: AsyncSession, version_id: uuid.UUID) -> CardVersion:
    version = await session.get(CardVersion, version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Версия карточки не найдена"
        )
    return version


async def _build_feedback_input(
    session: AsyncSession, version: CardVersion, text: str
) -> FeedbackInput:
    """Собрать контекст для разбора: концепция карточки [3] + стиль бренда проекта."""
    concept: CardConcept | None = None
    brand_style: str | None = None
    card = await session.get(Card, version.card_id)
    if card is not None:
        if card.concept_json is not None:
            concept = CardConcept.model_validate(card.concept_json)
        card_set = await session.get(CardSet, card.card_set_id)
        if card_set is not None:
            project = await session.get(Project, card_set.project_id)
            if project is not None:
                brand_style = project.brand_style
    return FeedbackInput(feedback_text=text, concept=concept, brand_style=brand_style)


@router.post(
    "/card-versions/{version_id}/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    version_id: uuid.UUID, payload: FeedbackCreate, session: SessionDep
) -> FeedbackRead:
    """Принять фидбэк менеджера к версии карточки и разобрать его LLM (стадия [9]).

    Текст сохраняется всегда; если разбор удался — в ``parsed_action_json`` ложится
    структурированное действие (стадия + дельты) для последующей перегенерации.
    """
    version = await _get_version_or_404(session, version_id)
    feedback_input = await _build_feedback_input(session, version, payload.text)

    provider = get_llm_provider()
    try:
        parsed, _response = await parse_feedback(provider, feedback_input, model=payload.model)
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка разбора фидбэка: {exc}",
        ) from exc

    feedback = Feedback(
        card_version_id=version.id,
        text=payload.text,
        parsed_action_json=parsed.model_dump(mode="json"),
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return FeedbackRead.model_validate(feedback)


@router.post(
    "/feedback/{feedback_id}/regenerate",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_from_feedback(
    feedback_id: uuid.UUID, payload: FeedbackRegenerateRequest, session: SessionDep
) -> JobRead:
    """Поставить перегенерацию адресуемой стадии по разобранному фидбэку (стадия [9]).

    Стадию определяет ``parsed_action.target_stage``: концепция [3]/изображение [5]
    регенерируют изображение, текст [6] — только наложенный текст (товар сохраняется).
    Стадии ideas/unknown требуют ручного решения → 409. Тяжёлую работу делает worker;
    создаётся новая версия карточки (история сохраняется). Возвращает задачу (Job).
    """
    feedback = await session.get(Feedback, feedback_id)
    if feedback is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фидбэк не найден")
    parsed = feedback.parsed_action_json
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Фидбэк не разобран (стадия [9]) — нечего перегенерировать",
        )
    target_stage = parsed.get("target_stage")
    if target_stage not in _AUTO_REGEN_STAGES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Стадия {target_stage!r} не перегенерируется автоматически "
                "(требуется ручное решение менеджера)"
            ),
        )

    job = Job(
        type=job_const.JOB_FEEDBACK_REGEN,
        status=job_const.JOB_PENDING,
        payload_json={
            "feedback_id": str(feedback_id),
            "target_stage": target_stage,
            "template_key": payload.template_key,
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    enqueue_feedback_regen(job.id, feedback_id, template_key=payload.template_key)
    return JobRead.model_validate(job)


@router.get(
    "/card-versions/{version_id}/feedback",
    response_model=list[FeedbackRead],
)
async def list_feedback(version_id: uuid.UUID, session: SessionDep) -> list[FeedbackRead]:
    """История фидбэка к версии карточки (404, если версии нет)."""
    await _get_version_or_404(session, version_id)
    result = await session.scalars(
        select(Feedback)
        .where(Feedback.card_version_id == version_id)
        .order_by(Feedback.created_at)
    )
    return [FeedbackRead.model_validate(item) for item in result.all()]

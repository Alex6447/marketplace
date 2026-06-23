"""Celery-задачи стадий пайплайна (docs/plan.md, разделы 3 и 6).

Единицы работы (каждая владеет своей записью :class:`Job`):
- :func:`asset_matting_task` — стадия [4] (удаление фона/маска);
- :func:`card_image_task` — стадия [5] (генерация изображения карточки);
- :func:`finalize_card_set_task` — финализатор `chord` для набора карточек.

Многостадийные сборки выражаются Celery-примитивами: генерация набора карточек —
это `chord(group(card_image…), finalize)` (параллельные карточки + общий финал), а
композитинг с предварительной подготовкой ассета — `chain(asset_matting, card_image)`.
Канвас собирает :func:`build_card_set_canvas`.
"""

from __future__ import annotations

import uuid
from typing import Any

from celery import chain, chord, group

from marketplace_shared import jobs as job_const
from marketplace_shared.db import Job, sync_session_scope
from marketplace_worker import jobs as job_lifecycle
from marketplace_worker import stages
from marketplace_worker.celery_app import app


def _load_job(session: Any, job_id: str) -> Job:
    job = session.get(Job, uuid.UUID(job_id))
    if job is None:
        raise ValueError(f"Job {job_id} не найдена")
    return job


@app.task(name=job_const.TASK_ASSET_MATTING, bind=True)
def asset_matting_task(self: Any, job_id: str, asset_id: str, model: str | None = None) -> dict:
    """Стадия [4]: удаление фона и маска товара (владеет своей Job)."""
    with sync_session_scope() as session:
        job = _load_job(session, job_id)
        job_lifecycle.mark_running(session, job, stage="asset_matting", progress=10)
        try:
            result = stages.run_asset_matting(session, uuid.UUID(asset_id), model=model)
        except Exception as exc:
            job_lifecycle.mark_failure(session, job, str(exc))
            raise
        job_lifecycle.mark_success(session, job, result)
        return result


@app.task(name=job_const.TASK_CARD_IMAGE, bind=True)
def card_image_task(
    self: Any,
    job_id: str,
    card_id: str,
    *,
    mode: str = "edit",
    model: str | None = None,
    seed: int | None = None,
    size: str | None = None,
    use_references: bool = True,
) -> dict:
    """Стадия [5]: генерация изображения карточки (владеет своей Job)."""
    with sync_session_scope() as session:
        job = _load_job(session, job_id)
        job_lifecycle.mark_running(session, job, stage="image_gen", progress=20)
        try:
            result = stages.run_card_image(
                session,
                uuid.UUID(card_id),
                mode=mode,
                model=model,
                seed=seed,
                size=size,
                use_references=use_references,
            )
        except Exception as exc:
            job_lifecycle.mark_failure(session, job, str(exc))
            raise
        job_lifecycle.mark_success(session, job, result)
        return result


@app.task(name=job_const.TASK_CARD_TEXT, bind=True)
def card_text_overlay_task(
    self: Any, job_id: str, card_version_id: str, *, template_key: str | None = None
) -> dict:
    """Стадия [6]: наложение текста концепции на изображение версии (владеет своей Job)."""
    with sync_session_scope() as session:
        job = _load_job(session, job_id)
        job_lifecycle.mark_running(session, job, stage="text_overlay", progress=20)
        try:
            result = stages.run_card_text_overlay(
                session, uuid.UUID(card_version_id), template_key=template_key
            )
        except Exception as exc:
            job_lifecycle.mark_failure(session, job, str(exc))
            raise
        job_lifecycle.mark_success(session, job, result)
        return result


@app.task(name=job_const.TASK_CARD_SET_FINALIZE, bind=True)
def finalize_card_set_task(self: Any, child_results: list[dict], parent_job_id: str) -> dict:
    """Финализатор chord: помечает родительскую задачу набора успехом.

    Первым аргументом chord передаёт список результатов задач группы.
    """
    with sync_session_scope() as session:
        job = _load_job(session, parent_job_id)
        result = {"cards": child_results, "count": len(child_results)}
        job_lifecycle.mark_success(session, job, result)
        return result


def build_card_set_canvas(
    parent_job_id: str, items: list[dict[str, Any]], *, prepare: bool = False
):
    """Собрать Celery-канвас генерации набора карточек: `chord(group(...), finalize)`.

    ``items`` — по карточке: ``{image_job_id, card_id, mode, model, seed, size,
    use_references}`` (+ ``matting_job_id``/``asset_id`` при ``prepare``). При
    ``prepare=True`` каждая карточка — `chain(asset_matting, card_image)`: сначала
    маска (стадия [4]), затем композитинг (стадия [5]).
    """
    branches = []
    for item in items:
        image_sig = card_image_task.s(
            item["image_job_id"],
            item["card_id"],
            mode=item.get("mode", "edit"),
            model=item.get("model"),
            seed=item.get("seed"),
            size=item.get("size"),
            use_references=item.get("use_references", True),
        )
        if prepare:
            matting_sig = asset_matting_task.s(item["matting_job_id"], item["asset_id"])
            # card_image — immutable (.si): не принимает результат matting как аргумент.
            branches.append(chain(matting_sig, image_sig.set(immutable=True)))
        else:
            branches.append(image_sig)
    return chord(group(branches), finalize_card_set_task.s(parent_job_id))

"""Постановка задач в очередь из тонкого API (docs/plan.md, разделы 2 и 6).

API не импортирует код воркера: задачи ставятся **по имени** (`send_task` и
name-based `signature`), а исполняет их отдельный worker-процесс. Так тонкий образ
API остаётся без тяжёлых зависимостей. Имена задач — общий контракт из
:mod:`marketplace_shared.jobs`.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from celery import Celery, chain, chord, group, signature

from marketplace_api.config import get_settings
from marketplace_shared import jobs as job_const


@lru_cache
def get_celery() -> Celery:
    """Singleton-клиент Celery для постановки задач (брокер/бэкенд — Redis)."""
    settings = get_settings()
    app = Celery("marketplace_api", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
    )
    return app


def enqueue_asset_matting(
    job_id: uuid.UUID, asset_id: uuid.UUID, *, model: str | None = None
) -> None:
    """Поставить стадию [4] (удаление фона/маска) для ассета."""
    get_celery().send_task(
        job_const.TASK_ASSET_MATTING,
        args=[str(job_id), str(asset_id)],
        kwargs={"model": model},
    )


def enqueue_card_image(
    job_id: uuid.UUID,
    card_id: uuid.UUID,
    *,
    mode: str,
    model: str | None,
    seed: int | None,
    size: str | None,
    use_references: bool,
) -> None:
    """Поставить стадию [5] (генерация изображения карточки)."""
    get_celery().send_task(
        job_const.TASK_CARD_IMAGE,
        args=[str(job_id), str(card_id)],
        kwargs={
            "mode": mode,
            "model": model,
            "seed": seed,
            "size": size,
            "use_references": use_references,
        },
    )


def enqueue_card_set(
    parent_job_id: uuid.UUID, items: list[dict[str, Any]], *, prepare: bool
) -> None:
    """Поставить генерацию набора карточек: `chord(group(card_image…), finalize)`.

    При ``prepare=True`` каждая карточка — `chain(asset_matting, card_image)`. Канвас
    собирается name-based сигнатурами (без импорта задач воркера).
    """
    celery = get_celery()
    branches = []
    for item in items:
        image_sig = signature(
            job_const.TASK_CARD_IMAGE,
            args=[item["image_job_id"], item["card_id"]],
            kwargs={
                "mode": item.get("mode", "edit"),
                "model": item.get("model"),
                "seed": item.get("seed"),
                "size": item.get("size"),
                "use_references": item.get("use_references", True),
            },
            app=celery,
        )
        if prepare:
            matting_sig = signature(
                job_const.TASK_ASSET_MATTING,
                args=[item["matting_job_id"], item["asset_id"]],
                app=celery,
            )
            branches.append(chain(matting_sig, image_sig.set(immutable=True)))
        else:
            branches.append(image_sig)
    finalize_sig = signature(
        job_const.TASK_CARD_SET_FINALIZE, args=[str(parent_job_id)], app=celery
    )
    chord(group(branches), finalize_sig).apply_async()

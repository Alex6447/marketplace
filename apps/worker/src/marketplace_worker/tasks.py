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

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from celery import chain, chord, group
from sqlalchemy.orm import Session

from marketplace_shared import jobs as job_const
from marketplace_shared.db import Job, sync_session_scope
from marketplace_shared.observability import get_tracer
from marketplace_shared.providers.errors import TransientProviderError
from marketplace_worker import jobs as job_lifecycle
from marketplace_worker import stages
from marketplace_worker.celery_app import app

log = logging.getLogger(__name__)

#: Максимум автоповторов транзиентной ошибки и параметры экспоненциального backoff.
MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2
_MAX_BACKOFF_SECONDS = 30

#: Подстроки в тексте ошибки, указывающие на временный сбой внешнего API.
_TRANSIENT_HINTS = (
    "timeout",
    "timed out",
    "rate limit",
    "429",
    "temporarily",
    "connection reset",
    "connection aborted",
    "502",
    "503",
    "504",
    "service unavailable",
)


def _load_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, uuid.UUID(job_id))
    if job is None:
        raise ValueError(f"Job {job_id} не найдена")
    return job


def _is_transient(exc: BaseException) -> bool:
    """Стоит ли повторять задачу: сетевой сбой/таймаут/429/5xx внешнего провайдера.

    Распознаёт явную :class:`TransientProviderError`, стандартные сетевые исключения,
    httpx-ошибки транспорта/таймаута и эвристику по тексту (для SDK, не выставляющих
    типизированных исключений). Постоянные ошибки (валидация, конфиг) не повторяются.
    """
    if isinstance(exc, TransientProviderError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    try:
        import httpx

        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
    except ImportError:  # pragma: no cover — httpx есть в зависимостях
        pass
    text = str(exc).lower()
    return any(hint in text for hint in _TRANSIENT_HINTS)


def _format_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def run_job_task(
    self: Any,
    job_id: str,
    stage: str,
    progress: int,
    work: Callable[[Session], dict],
) -> dict:
    """Прогнать стадию под управлением её :class:`Job`: статус, ретраи, логи.

    Единый каркас для стадий [4]/[5]/[6]/[9]: переводит задачу в running, исполняет
    ``work`` (синхронную стадию из :mod:`marketplace_worker.stages`), логирует
    длительность. Транзиентную ошибку повторяет с экспоненциальным backoff (до
    :data:`MAX_RETRIES`), помечая Job статусом ``retry``; постоянную — фиксирует как
    ``failure``. И то и другое логируется.
    """
    tracer = get_tracer()
    with sync_session_scope() as session:
        job = _load_job(session, job_id)
        job_lifecycle.mark_running(session, job, stage=stage, progress=progress)
        log.info("Стадия %s начата (job=%s)", stage, job_id)
        started = time.perf_counter()
        try:
            with tracer.span(stage, job_id=job_id, type=job.type):
                result = work(session)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            retries = self.request.retries
            if _is_transient(exc) and retries < MAX_RETRIES:
                attempt = retries + 1
                countdown = min(_MAX_BACKOFF_SECONDS, _BASE_BACKOFF_SECONDS * (2**retries))
                log.warning(
                    "Стадия %s (job=%s) транзиентная ошибка за %.1fs — повтор %d/%d через %ds: %s",
                    stage,
                    job_id,
                    elapsed,
                    attempt,
                    MAX_RETRIES,
                    countdown,
                    exc,
                )
                job_lifecycle.mark_retrying(session, job, _format_error(exc), attempt)
                # self.retry — идиоматичный Celery-повтор: бросает Retry с причиной exc.
                raise self.retry(exc=exc, countdown=countdown)  # noqa: B904
            log.error(
                "Стадия %s (job=%s) провалена за %.1fs: %s",
                stage,
                job_id,
                elapsed,
                exc,
                exc_info=True,
            )
            job_lifecycle.mark_failure(session, job, _format_error(exc))
            raise
        elapsed = time.perf_counter() - started
        log.info("Стадия %s готова за %.2fs (job=%s)", stage, elapsed, job_id)
        job_lifecycle.mark_success(session, job, result)
        return result


@app.task(name=job_const.TASK_ASSET_MATTING, bind=True)
def asset_matting_task(self: Any, job_id: str, asset_id: str, model: str | None = None) -> dict:
    """Стадия [4]: удаление фона и маска товара (владеет своей Job)."""
    return run_job_task(
        self,
        job_id,
        "asset_matting",
        10,
        lambda session: stages.run_asset_matting(session, uuid.UUID(asset_id), model=model),
    )


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
    return run_job_task(
        self,
        job_id,
        "image_gen",
        20,
        lambda session: stages.run_card_image(
            session,
            uuid.UUID(card_id),
            mode=mode,
            model=model,
            seed=seed,
            size=size,
            use_references=use_references,
        ),
    )


@app.task(name=job_const.TASK_CARD_TEXT, bind=True)
def card_text_overlay_task(
    self: Any, job_id: str, card_version_id: str, *, template_key: str | None = None
) -> dict:
    """Стадия [6]: наложение текста концепции на изображение версии (владеет своей Job)."""
    return run_job_task(
        self,
        job_id,
        "text_overlay",
        20,
        lambda session: stages.run_card_text_overlay(
            session, uuid.UUID(card_version_id), template_key=template_key
        ),
    )


@app.task(name=job_const.TASK_FEEDBACK_REGEN, bind=True)
def feedback_regen_task(
    self: Any, job_id: str, feedback_id: str, *, template_key: str | None = None
) -> dict:
    """Перегенерация адресуемой фидбэком стадии [9]→[3]/[5]/[6] (владеет своей Job)."""
    return run_job_task(
        self,
        job_id,
        "feedback_regen",
        15,
        lambda session: stages.run_feedback_regeneration(
            session, uuid.UUID(feedback_id), template_key=template_key
        ),
    )


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

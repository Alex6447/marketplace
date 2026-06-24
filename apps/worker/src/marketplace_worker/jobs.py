"""Управление жизненным циклом :class:`Job` из воркера (sync-сессия).

Тонкие функции переходов статуса задачи (docs_marketplace/plan.md, разделы 5–6). API создаёт
запись Job (async), воркер обновляет её здесь по ходу выполнения — статус, прогресс,
текущая стадия, результат/ошибка. Каждое изменение коммитится сразу, чтобы SSE-поток
API (отдельная сессия) видел прогресс в реальном времени.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from marketplace_shared import jobs as job_const
from marketplace_shared.db import Job


def mark_running(
    session: Session, job: Job, *, stage: str | None = None, progress: int = 0
) -> None:
    """Перевести задачу в статус running (начало выполнения)."""
    job.status = job_const.JOB_RUNNING
    job.progress = _clamp(progress)
    if stage is not None:
        job.stage = stage
    job.error = None
    session.commit()


def set_progress(session: Session, job: Job, progress: int, *, stage: str | None = None) -> None:
    """Обновить прогресс (0–100) и, опционально, метку текущей стадии."""
    job.progress = _clamp(progress)
    if stage is not None:
        job.stage = stage
    session.commit()


def mark_success(session: Session, job: Job, result: dict) -> None:
    """Завершить задачу успехом: статус success, прогресс 100, результат."""
    job.status = job_const.JOB_SUCCESS
    job.progress = 100
    job.result_json = result
    job.error = None
    session.commit()


def mark_retrying(session: Session, job: Job, error: str, attempt: int) -> None:
    """Пометить задачу как ожидающую повтора (транзиентная ошибка провайдера).

    Не терминальный статус: SSE-поток продолжается, прогресс сохраняется. ``attempt``
    — номер предстоящей попытки (для наблюдаемости).
    """
    job.status = job_const.JOB_RETRY
    job.error = f"попытка {attempt}: {error}"
    session.commit()


def mark_failure(session: Session, job: Job, error: str) -> None:
    """Завершить задачу ошибкой: статус failure, текст ошибки."""
    job.status = job_const.JOB_FAILURE
    job.error = error
    session.commit()


def _clamp(progress: int) -> int:
    return max(0, min(100, progress))

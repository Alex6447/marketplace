"""Статус и прогресс фоновых задач (docs/plan.md, раздел 6).

Эндпоинты:
- ``GET /jobs/{id}`` — текущее состояние задачи (для опроса);
- ``GET /jobs/{id}/events`` — поток прогресса по SSE (Server-Sent Events).

SSE выбран вместо WebSocket (раздел 2): однонаправленный поток сервер→клиент проще,
дружелюбен к nginx и авто-переподключению. Прогресс пишет worker в строку Job; здесь
мы периодически перечитываем её свежей сессией и шлём событие при изменении, пока
задача не достигнет терминального статуса.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import JobRead
from marketplace_shared import jobs as job_const
from marketplace_shared.db import Job, get_session
from marketplace_shared.db.session import get_sessionmaker

router = APIRouter(prefix="/jobs", tags=["jobs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: Интервал опроса строки Job для SSE и страховочный потолок времени потока.
_POLL_INTERVAL_SECONDS = 0.5
_MAX_STREAM_SECONDS = 600


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: uuid.UUID, session: SessionDep) -> JobRead:
    """Текущее состояние задачи (404, если задачи нет)."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return JobRead.model_validate(job)


def _sse(event: str, data: dict) -> str:
    """Сформировать одно SSE-событие."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _job_event_stream(job_id: uuid.UUID) -> AsyncIterator[str]:
    """Поток SSE: события прогресса до терминального статуса задачи."""
    maker = get_sessionmaker()
    last_snapshot: tuple | None = None
    waited = 0.0
    while waited <= _MAX_STREAM_SECONDS:
        async with maker() as session:
            job = await session.get(Job, job_id)
        if job is None:
            yield _sse("error", {"detail": "Задача не найдена"})
            return

        snapshot = (job.status, job.progress, job.stage)
        if snapshot != last_snapshot:
            yield _sse(
                "progress",
                {
                    "id": str(job.id),
                    "status": job.status,
                    "progress": job.progress,
                    "stage": job.stage,
                },
            )
            last_snapshot = snapshot

        if job.status in job_const.TERMINAL_STATUSES:
            yield _sse(
                "done",
                {
                    "id": str(job.id),
                    "status": job.status,
                    "result": job.result_json,
                    "error": job.error,
                },
            )
            return

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        waited += _POLL_INTERVAL_SECONDS


@router.get("/{job_id}/events")
async def stream_job_events(job_id: uuid.UUID, session: SessionDep) -> StreamingResponse:
    """SSE-поток прогресса задачи (404, если задачи нет на момент подписки)."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return StreamingResponse(
        _job_event_stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

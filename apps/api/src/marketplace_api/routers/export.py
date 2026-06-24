"""Экспорт/скачивание готовых карточек (docs/plan.md, разделы 6 и 7, «Итог MVP»).

Завершает пользовательский путь: проект → … → текст → фидбэк → **скачивание**.

Эндпоинты:
- ``GET /card-versions/{id}/download`` — скачать одну версию карточки (финал с
  текстом [6], иначе изображение [5]) как PNG;
- ``GET /card-sets/{id}/export`` — скачать весь комплект набора одним zip: по
  последней готовой версии каждой карточки + ``manifest.json`` с метаданными.

Сборка архива (:func:`build_export_archive`) — чистая функция (байты → байты),
тестируемая офлайн; роутер лишь собирает байты из MinIO (в threadpool, т.к. boto3
синхронный) и отдаёт готовый поток.
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_shared.db import Card, CardSet, CardVersion, get_session
from marketplace_shared.storage import S3Storage, get_storage

router = APIRouter(tags=["export"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[S3Storage, Depends(get_storage)]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    """Безопасный фрагмент имени файла из роли карточки (латиница/цифры/дефис)."""
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "card"


def _display_key(version: CardVersion) -> str | None:
    """Ключ изображения для отдачи: финал с текстом [6], иначе изображение [5]."""
    return version.final_s3_key or version.image_s3_key


def build_export_archive(entries: list[tuple[str, bytes]], manifest: dict[str, Any]) -> bytes:
    """Собрать zip из именованных PNG-карточек и ``manifest.json`` (чистая функция).

    ``entries`` — список ``(имя_файла, png_байты)``; имена уникализируются на случай
    совпадения ролей. Детерминированно (без таймстампов в именах) — удобно для тестов.
    """
    buffer = io.BytesIO()
    used: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            seen = used.get(name, 0)
            used[name] = seen + 1
            final_name = name if seen == 0 else f"{name.removesuffix('.png')}-{seen + 1}.png"
            zf.writestr(final_name, data)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue()


async def _get_version_or_404(session: AsyncSession, version_id: uuid.UUID) -> CardVersion:
    version = await session.get(CardVersion, version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Версия карточки не найдена"
        )
    return version


@router.get("/card-versions/{version_id}/download")
async def download_version(
    version_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> Response:
    """Скачать готовый вариант версии карточки (финал [6] или изображение [5]) как PNG."""
    version = await _get_version_or_404(session, version_id)
    key = _display_key(version)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У версии нет изображения (стадии [5]/[6]) — нечего скачивать",
        )
    data = await run_in_threadpool(storage.get_object, key)
    filename = f"card-{version.card_id}-v{version.version_no}.png"
    return Response(
        content=data,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/card-sets/{card_set_id}/export")
async def export_card_set(
    card_set_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> Response:
    """Скачать комплект набора одним zip: последняя готовая версия каждой карточки.

    Для каждой карточки берётся версия с наибольшим ``version_no``, имеющая
    изображение (предпочтительно финал с текстом [6]). Карточки без единой готовой
    версии в архив не попадают; если готовых нет вовсе — 409.
    """
    card_set = await session.get(CardSet, card_set_id)
    if card_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Набор не найден")

    # Карточки набора в порядке отображения + их версии (по убыванию номера —
    # первая с изображением и будет «последней готовой»).
    rows = list(
        await session.scalars(
            select(CardVersion)
            .join(Card, CardVersion.card_id == Card.id)
            .where(Card.card_set_id == card_set_id)
            .order_by(Card.order, CardVersion.version_no.desc())
        )
    )
    cards = {
        c.id: c
        for c in await session.scalars(
            select(Card).where(Card.card_set_id == card_set_id).order_by(Card.order)
        )
    }

    # По карточке — первая (т.е. самая свежая) версия с изображением.
    chosen: dict[uuid.UUID, CardVersion] = {}
    for v in rows:
        if _display_key(v) and v.card_id not in chosen:
            chosen[v.card_id] = v

    if not chosen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="В наборе нет готовых карточек для экспорта (сгенерируйте изображения)",
        )

    # Сборка идёт в порядке карточек набора.
    ordered = sorted(chosen.values(), key=lambda v: (cards[v.card_id].order, v.version_no))

    def _collect() -> bytes:
        entries: list[tuple[str, bytes]] = []
        manifest_cards: list[dict[str, Any]] = []
        for v in ordered:
            card = cards[v.card_id]
            key = _display_key(v)
            assert key is not None  # отфильтровано выше
            data = storage.get_object(key)
            filename = f"{card.order + 1:02d}-{_slug(card.role)}.png"
            overlay = v.gen_params_json.get("text_overlay") or {}
            qa = v.qa_report_json or {}
            entries.append((filename, data))
            manifest_cards.append(
                {
                    "filename": filename,
                    "card_id": str(card.id),
                    "role": card.role,
                    "order": card.order,
                    "version_id": str(v.id),
                    "version_no": v.version_no,
                    "has_text": bool(v.final_s3_key),
                    "template": overlay.get("template"),
                    "qa_status": qa.get("status"),
                }
            )
        manifest = {
            "card_set_id": str(card_set_id),
            "count": len(entries),
            "cards": manifest_cards,
        }
        return build_export_archive(entries, manifest)

    archive = await run_in_threadpool(_collect)
    filename = f"cardset-{card_set_id}.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

"""Контент-адресуемый кэш артефактов стадий пайплайна (docs_marketplace/plan.md, разделы 1, 3).

Каждая тяжёлая стадия ([4] маска/вырез, [5] editing/композитинг) детерминирована
своими входами: одни и те же фото/вырез/референсы + концепция + параметры провайдера
(модель, размер, seed) дают один и тот же артефакт. Поэтому артефакт адресуется по
**хэшу входов**: перед дорогим вызовом провайдера стадия считает digest и смотрит в
хранилище — при попадании переиспользует готовый объект, не дёргая провайдера.

Это и есть механизм «правка только нужной стадии» (стадия [9], цикл обратной связи):
при перегенерации карточки стадии, чьи входы не изменились, отдают артефакт из кэша —
оплачивается и пересчитывается только реально изменившаяся стадия.

Здесь — провайдеро- и хранилищенезависимые примитивы:
- :func:`stage_digest` / :func:`artifact_key` — чистые функции вычисления ключа;
- :class:`StageCache` — тонкая обёртка над хранилищем (через :class:`StorageLike`),
  тестируемая на фейковом storage без MinIO.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    """Настройки пайплайна, читаемые из окружения (`.env`).

    Префикс ключей — ``PIPELINE_`` (поле ``cache_enabled`` → ``PIPELINE_CACHE_ENABLED``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="pipeline_",
        extra="ignore",
    )

    #: Включён ли контент-адресуемый кэш артефактов стадий. Можно выключить для
    #: отладки/принудительного пересчёта, не меняя код.
    cache_enabled: bool = True
    #: Префикс ключей кэша в бакете (изоляция от пользовательских артефактов).
    cache_prefix: str = "cache"


@lru_cache
def get_pipeline_settings() -> PipelineSettings:
    """Singleton-доступ к настройкам пайплайна (кэш на время жизни процесса)."""
    return PipelineSettings()


def _canonical(params: Mapping[str, Any]) -> bytes:
    """Канонический (стабильный по порядку ключей) JSON-байтстрим параметров.

    ``sort_keys`` делает результат независимым от порядка вставки ключей, поэтому
    одинаковые по смыслу входы дают одинаковый digest.
    """
    return json.dumps(
        params, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def blob_digest(data: bytes) -> str:
    """SHA-256 байтов изображения (hex). Вынесено для переиспользования/тестов."""
    return hashlib.sha256(data).hexdigest()


def stage_digest(
    stage: str,
    *,
    params: Mapping[str, Any] | None = None,
    blobs: Sequence[bytes] = (),
) -> str:
    """Вычислить контент-адрес стадии из её входов (чистая, детерминированная).

    ``params`` — скалярные/JSON-входы (модель, размер, seed, концепция, brand_style);
    ``blobs`` — бинарные входы (фото товара, вырез, референсы). Порядок ``blobs``
    значим — передавайте его стабильным (например, отсортированным по id ассета).
    """
    h = hashlib.sha256()
    h.update(stage.encode("utf-8"))
    h.update(b"\0")
    h.update(_canonical(params or {}))
    for blob in blobs:
        h.update(b"\0")
        h.update(blob_digest(blob).encode("ascii"))
    return h.hexdigest()


def artifact_key(stage: str, digest: str, suffix: str = "png", *, prefix: str = "cache") -> str:
    """Ключ артефакта в хранилище: ``{prefix}/{stage}/{digest}.{suffix}``.

    ``suffix`` может быть составным (``mask.png``/``cutout.png``) — это сохраняет
    соглашение «вырез — сосед маски по имени» (``*.mask.png`` ↔ ``*.cutout.png``).
    """
    return f"{prefix}/{stage}/{digest}.{suffix}"


class StorageLike(Protocol):
    """Минимальный интерфейс хранилища, нужный кэшу (реализуется ``S3Storage``)."""

    def put_object(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    def get_object(self, key: str) -> bytes: ...

    def object_exists(self, key: str) -> bool: ...


class StageCache:
    """Контент-адресуемый кэш артефактов поверх S3-совместимого хранилища.

    Не знает о конкретных стадиях — оперирует ``stage``/``digest``/``suffix``. Логика
    «считать или взять из кэша» остаётся в стадиях воркера, где есть провайдер и БД.
    """

    def __init__(self, storage: StorageLike, *, prefix: str = "cache") -> None:
        self._storage = storage
        self._prefix = prefix

    def key(self, stage: str, digest: str, suffix: str = "png") -> str:
        """Ключ артефакта для стадии/диджеста (см. :func:`artifact_key`)."""
        return artifact_key(stage, digest, suffix, prefix=self._prefix)

    def exists(self, key: str) -> bool:
        """Есть ли артефакт по ключу в хранилище (HEAD-запрос, без чтения тела)."""
        return self._storage.object_exists(key)

    def get(self, key: str) -> bytes:
        """Прочитать артефакт по ключу (вызывать после :meth:`exists`)."""
        return self._storage.get_object(key)

    def put(self, key: str, data: bytes, content_type: str = "image/png") -> None:
        """Сохранить артефакт по контент-адресуемому ключу."""
        self._storage.put_object(key, data, content_type)

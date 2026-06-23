"""Клиент S3-совместимого хранилища (MinIO / S3) на boto3.

Синхронный по природе (boto3); в async-эндпоинтах FastAPI вызовы оборачиваются
в threadpool (см. `apps/api`). Path-style адресация (`s3={"addressing_style":
"path"}`) обязательна для MinIO, у которого нет virtual-hosted поддоменов бакета.
"""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from marketplace_shared.storage.config import StorageSettings, get_storage_settings

#: Время жизни presigned-URL по умолчанию (1 час). Достаточно для скачивания
#: и для передачи во внешний image-провайдер (стадия [5]).
DEFAULT_URL_EXPIRES = 3600


class S3Storage:
    """Обёртка над S3-бакетом: загрузка объектов и presigned-URL."""

    def __init__(self, settings: StorageSettings) -> None:
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @property
    def bucket(self) -> str:
        """Имя бакета, в который пишутся объекты."""
        return self._bucket

    def ensure_bucket(self) -> None:
        """Создать бакет, если его ещё нет (идемпотентно).

        В docker-compose бакет создаёт сервис `minio-init`; метод полезен для
        локального запуска без полного compose-стека и в тестах.
        """
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def put_object(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Записать объект по ключу `key`."""
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def get_object(self, key: str) -> bytes:
        """Прочитать объект по ключу `key` целиком в память.

        Нужен стадии [5]: фото товара читается из хранилища и передаётся
        image-провайдеру inline-байтами (без presigned-round-trip), а результат
        сохраняется обратно. Артефакты карточек — небольшие изображения.
        """
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def object_exists(self, key: str) -> bool:
        """Проверить наличие объекта по ключу без чтения тела (HEAD).

        Нужен контент-адресуемому кэшу стадий (:class:`marketplace_shared.pipeline.
        StageCache`): попадание в кэш — это существующий объект по ключу-хэшу входов.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError:
            return False
        return True

    def presigned_get_url(self, key: str, expires: int = DEFAULT_URL_EXPIRES) -> str:
        """Сгенерировать presigned-URL для скачивания объекта по ключу `key`."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires,
        )

    def delete_object(self, key: str) -> None:
        """Удалить объект по ключу `key` (идемпотентно на стороне S3)."""
        self._client.delete_object(Bucket=self._bucket, Key=key)


@lru_cache
def get_storage() -> S3Storage:
    """Singleton-клиент хранилища (кэш на время жизни процесса)."""
    return S3Storage(get_storage_settings())

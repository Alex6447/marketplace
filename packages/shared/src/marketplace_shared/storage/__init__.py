"""Хранилище файлов/изображений (MinIO / S3 API).

Тонкая обёртка над S3-совместимым хранилищем: загрузка ассетов товара (фото,
референсы) и выдача presigned-URL для скачивания/передачи image-провайдеру.
Один и тот же клиент используется и API (загрузка фото), и worker'ом (чтение/
запись артефактов стадий).
"""

from marketplace_shared.storage.config import StorageSettings, get_storage_settings
from marketplace_shared.storage.s3 import S3Storage, get_storage

__all__ = [
    "StorageSettings",
    "get_storage_settings",
    "S3Storage",
    "get_storage",
]

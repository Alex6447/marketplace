"""Централизованная настройка логирования для API и worker (docs/plan.md, Этап 5).

Единый формат и уровень логов на оба сервиса: уровень из ``LOG_LEVEL`` (по умолчанию
``INFO``). Идемпотентно — повторный вызов не плодит обработчики. Модули логируют через
стандартный ``logging.getLogger(__name__)``; здесь только конфигурация корня.

Не тащит внешних зависимостей: структурный трейсинг/учёт стоимости (Langfuse/OTel) —
отдельный провайдеро-независимый слой :mod:`marketplace_shared.observability`.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False

#: Формат строки лога: время, уровень, сервис, логгер, сообщение.
_FORMAT = "%(asctime)s %(levelname)-7s [%(service)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _ServiceFilter(logging.Filter):
    """Добавляет имя сервиса в каждую запись (для формата ``[%(service)s]``)."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self._service
        return True


def configure_logging(*, service: str, level: str | None = None) -> None:
    """Настроить корневой логгер один раз за процесс.

    ``service`` — метка сервиса в логах (``api`` / ``worker``). ``level`` переопределяет
    ``LOG_LEVEL`` из окружения. Безопасно вызывать многократно (напр. из тестов).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    resolved = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    handler.addFilter(_ServiceFilter(service))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(resolved)
    _CONFIGURED = True

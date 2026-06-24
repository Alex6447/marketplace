"""Провайдеро-независимый трейсинг пайплайна (docs/plan.md, разделы 2 и 7, Этап 5).

Как и LLM/Image-провайдеры, наблюдаемость скрыта за абстракцией: пайплайн открывает
span на стадию и пишет атрибуты (job, карточка, длительность, расход), не зная, куда
они уходят. Бэкенд выбирается конфигом ``OBSERVABILITY_PROVIDER``:

- ``none`` (дефолт) — :class:`NoOpTracer`, ничего не отправляет (нулевые накладные);
- ``logging`` — пишет span'ы в обычный лог (полезно локально/в закрытом контуре);
- ``langfuse`` / ``otel`` — каркас под внешние трейсеры; их клиенты — тяжёлые
  опциональные зависимости (Этап 6/прод). Если библиотека не установлена, безопасно
  деградируем до ``logging`` с предупреждением, не роняя пайплайн.

Так трейсинг включается без правки кода стадий и без обязательных внешних зависимостей.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)


class Tracer(ABC):
    """Абстракция трейсера: span на операцию и точечные события."""

    @abstractmethod
    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[None]:
        """Контекст-менеджер вокруг операции (стадии). Атрибуты — произвольные метки."""
        raise NotImplementedError

    @abstractmethod
    def event(self, name: str, **attributes: Any) -> None:
        """Точечное событие (например, попадание в кэш, ретрай)."""
        raise NotImplementedError


class NoOpTracer(Tracer):
    """Ничего не делает — нулевые накладные, дефолт для офлайна/MVP."""

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[None]:
        yield

    def event(self, name: str, **attributes: Any) -> None:
        return


class LoggingTracer(Tracer):
    """Пишет span'ы и события в лог (длительность + атрибуты). Без внешних сервисов."""

    def __init__(self, level: int = logging.INFO) -> None:
        self._level = level

    @staticmethod
    def _fmt(attributes: dict[str, Any]) -> str:
        return " ".join(f"{k}={v}" for k, v in attributes.items())

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[None]:
        started = time.perf_counter()
        log.log(self._level, "span ▶ %s %s", name, self._fmt(attributes))
        try:
            yield
        except Exception as exc:
            elapsed = time.perf_counter() - started
            log.log(self._level, "span ✖ %s за %.2fs: %s", name, elapsed, exc)
            raise
        else:
            elapsed = time.perf_counter() - started
            log.log(self._level, "span ✓ %s за %.2fs", name, elapsed)

    def event(self, name: str, **attributes: Any) -> None:
        log.log(self._level, "event · %s %s", name, self._fmt(attributes))


@lru_cache
def get_tracer() -> Tracer:
    """Трейсер по ``OBSERVABILITY_PROVIDER`` (singleton на процесс).

    Неизвестное значение и недоступные внешние бэкенды деградируют до безопасного
    варианта (``logging`` с предупреждением), чтобы наблюдаемость никогда не роняла
    основной пайплайн.
    """
    provider = (os.environ.get("OBSERVABILITY_PROVIDER") or "none").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return NoOpTracer()
    if provider == "logging":
        return LoggingTracer()
    if provider in {"langfuse", "otel", "opentelemetry"}:
        # Клиенты Langfuse/OTel — тяжёлые опциональные зависимости (Этап 6/прод).
        # Пока они не подключены, не роняем пайплайн: логируем span'ы локально.
        log.warning(
            "OBSERVABILITY_PROVIDER=%s выбран, но клиент не подключён — "
            "использую логирующий трейсер (см. docs/plan.md, Этап 6)",
            provider,
        )
        return LoggingTracer()
    log.warning("Неизвестный OBSERVABILITY_PROVIDER=%r — трейсинг отключён", provider)
    return NoOpTracer()

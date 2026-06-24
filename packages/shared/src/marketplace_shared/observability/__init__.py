"""Наблюдаемость пайплайна: учёт стоимости и трейсинг (docs/plan.md, Этап 5).

Провайдеро-независимо, как и остальная архитектура:
- :mod:`marketplace_shared.observability.cost` — оценка стоимости вызова из
  :class:`~marketplace_shared.providers.contracts.Usage` (токены/изображения → USD);
- :mod:`marketplace_shared.observability.tracing` — абстракция трейсера со
  no-op-дефолтом и опциональными бэкендами (Langfuse/OTel) по конфигу.

Внешних зависимостей по умолчанию не тянет: трейсинг включается переменной
окружения, ценовая таблица — обычные данные.
"""

from __future__ import annotations

from .cost import (
    ServiceKind,
    apply_estimated_cost,
    estimate_image_cost,
    estimate_llm_cost,
)
from .tracing import (
    NoOpTracer,
    Tracer,
    get_tracer,
)

__all__ = [
    "ServiceKind",
    "estimate_llm_cost",
    "estimate_image_cost",
    "apply_estimated_cost",
    "Tracer",
    "NoOpTracer",
    "get_tracer",
]

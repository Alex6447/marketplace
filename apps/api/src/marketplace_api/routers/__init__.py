"""HTTP-роутеры API.

Каждый модуль — отдельная зона ответственности (health, проекты, товары, карточки,
jobs/SSE…). По мере реализации Этапов 1–5 сюда добавляются роутеры эндпоинтов из
docs_marketplace/plan.md (раздел 6). Сейчас — только health.
"""

from marketplace_api.routers import health

__all__ = ["health"]

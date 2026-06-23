"""Точка входа FastAPI — тонкий API-сервис.

Конфиг через pydantic-settings, CORS для фронтенд-дашборда, роутеры под префиксом
/api. CRUD проектов/товаров/ассетов (Этап 1) подключён; стадии генерации и jobs/SSE
(docs/plan.md, раздел 6) добавляются на Этапах 2–5.
"""

import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from marketplace_api import __version__
from marketplace_api.config import get_settings
from marketplace_api.routers import (
    assets,
    cards,
    generate,
    health,
    ideas,
    jobs,
    products,
    projects,
)

# Windows: async-драйвер psycopg несовместим с ProactorEventLoop (дефолт на Windows).
# Переключаем политику на SelectorEventLoop ДО создания цикла uvicorn'ом. На Linux
# (Docker) условие ложно — no-op. См. заметку к модели данных в docs/plan.md (Этап 1).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()

app = FastAPI(title="Marketplace Cards API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Бизнес-роутеры — под префиксом /api.
app.include_router(health.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(ideas.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(generate.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness-проба контейнера: приложение поднялось и отвечает."""
    return {"status": "ok"}

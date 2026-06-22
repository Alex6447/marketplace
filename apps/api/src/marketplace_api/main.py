"""Точка входа FastAPI — тонкий API-сервис.

Каркас Этапа 0: конфиг через pydantic-settings, CORS для фронтенд-дашборда,
роутеры под префиксом /api. Бизнес-эндпоинты (проекты, товары, карточки, jobs/SSE
из docs/plan.md, раздел 6) и CRUD добавляются на Этапах 1–5.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from marketplace_api import __version__
from marketplace_api.config import get_settings
from marketplace_api.routers import health

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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness-проба контейнера: приложение поднялось и отвечает."""
    return {"status": "ok"}

"""Health-роутер: liveness/readiness под префиксом /api.

`/healthz` остаётся на корне (вне префикса) как стандартная liveness-проба
для контейнера и docker-compose healthcheck.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Ответ health-эндпоинта."""

    status: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Readiness-проба под префиксом /api — доступна фронтенду для проверки связи."""
    return HealthResponse(status="ok")

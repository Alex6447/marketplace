"""Точка входа FastAPI.

Сейчас — минимальный каркас с health-check, достаточный чтобы собрать и запустить
тонкий образ. Полноценный каркас (конфиг через pydantic-settings, роутеры раздела 6
плана, SSE-прогресс, CRUD) добавляется на следующем пункте Этапа 0
«Каркас FastAPI + React».
"""

from fastapi import FastAPI

from marketplace_api import __version__

app = FastAPI(title="Marketplace Cards API", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness-проба: подтверждает, что тонкий образ собран и приложение поднялось."""
    return {"status": "ok"}

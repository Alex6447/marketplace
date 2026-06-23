"""Celery-приложение воркера (docs/plan.md, раздел 2).

Брокер и бэкенд — Redis. Стадии пайплайна оформлены как задачи в :mod:`marketplace_
worker.tasks` (стадии [4]/[5]); многостадийные сборки выражаются Celery-примитивами
`chain`/`group`/`chord`. Сериализация — JSON (никаких pickle). Режим `task_always_eager`
включается переменной `CELERY_TASK_ALWAYS_EAGER` для тестов/офлайн-прогона без брокера.
"""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


app = Celery("marketplace", broker=REDIS_URL, backend=REDIS_URL)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_always_eager=_truthy(os.environ.get("CELERY_TASK_ALWAYS_EAGER")),
    task_eager_propagates=True,
)

# Регистрируем задачи в приложении (импорт ради side-effect декораторов @app.task).
# Импорт после создания `app`: tasks.py берёт уже готовый `app` — цикла нет.
from marketplace_worker import tasks as _tasks  # noqa: E402,F401  (регистрация задач)


@app.task(name="marketplace.ping")
def ping() -> str:
    """Health-задача: подтверждает, что воркер принимает и выполняет задачи."""
    return "pong"

"""Celery-приложение воркера.

Сейчас — минимальный каркас с health-задачей, достаточный чтобы собрать и запустить
тяжёлый образ. Реальные стадии пайплайна (idea/concept → asset → image → text → QA,
см. docs/plan.md, раздел 3) и провайдер-абстракции подключаются на Этапах 1–5.
"""

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery("marketplace", broker=REDIS_URL, backend=REDIS_URL)


@app.task(name="marketplace.ping")
def ping() -> str:
    """Health-задача: подтверждает, что воркер принимает и выполняет задачи."""
    return "pong"

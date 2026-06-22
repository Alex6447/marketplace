# syntax=docker/dockerfile:1
# Тяжёлый образ воркера: стадии пайплайна (image/LLM/текст/QA). Отдельно от тонкого
# API, чтобы ML/браузерные зависимости не тянулись в каждый деплой API.
# ⚠️ Контекст сборки — КОРЕНЬ репозитория (нужны корневой uv.lock и packages/shared).
#
# Базовый набор намеренно лёгкий (celery + pillow). Тяжёлые слои включаются
# экстра-зависимостями из apps/worker/pyproject.toml, заменив `--package` ниже на:
#   --extra render  → Playwright + Chromium (Этап 3, наложение текста);
#                     дополнительно нужен RUN playwright install --with-deps chromium
#   --extra local   → torch/torchvision (Этап 6, локальные модели, требует GPU);
#                     для CUDA — сменить базовый образ на nvidia/cuda + Python.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Слой зависимостей: только манифесты воркспейса → кэшируется отдельно от кода.
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/
COPY apps/worker/pyproject.toml apps/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package marketplace-worker

# 2) Слой кода: исходники воркера и общего пакета.
COPY packages/shared packages/shared
COPY apps/worker apps/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package marketplace-worker

ENV PATH="/app/.venv/bin:$PATH"
CMD ["celery", "-A", "marketplace_worker.celery_app:app", "worker", "--loglevel=info"]

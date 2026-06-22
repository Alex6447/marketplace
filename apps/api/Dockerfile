# syntax=docker/dockerfile:1
# Тонкий образ API: FastAPI без torch/CUDA — быстрый деплой, только оркестрация.
# ⚠️ Контекст сборки — КОРЕНЬ репозитория (нужны корневой uv.lock и пакет
#    packages/shared из uv-воркспейса). См. docker-compose.yml: build.context = "."
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Слой зависимостей: только манифесты воркспейса → кэшируется отдельно от кода.
COPY pyproject.toml uv.lock ./
COPY packages/shared/pyproject.toml packages/shared/
COPY apps/api/pyproject.toml apps/api/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-workspace --package marketplace-api

# 2) Слой кода: исходники тонкого API и общего пакета.
COPY packages/shared packages/shared
COPY apps/api apps/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package marketplace-api

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "marketplace_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

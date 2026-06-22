# apps/worker — GPU/CPU Worker (тяжёлый образ)

Celery-воркер (Python 3.12). **Тяжёлый образ** (`torch`/`CUDA`/ComfyUI-клиент при
local-режиме). Выполняет стадии пайплайна генерации (см. раздел 3 плана): идеи и
концепции (LLM), подготовка ассетов, генерация изображения с сохранением товара,
наложение текста (Playwright), QA-проверки.

> `pyproject.toml` (пакет `marketplace-worker` в uv-воркспейсе) и `Dockerfile` уже
> на месте. Сейчас Celery-приложение — минимальный каркас с health-задачей
> `marketplace.ping`. Реальные стадии пайплайна подключаются на Этапах 1–5.

## Назначение
- Изолированные перезапускаемые стадии пайплайна, артефакты сохраняются в MinIO.
- Провайдеро-независимость: работа через `ImageProvider` / `LLMProvider`
  (hosted ⇄ local), см. раздел 4 плана.

## Структура и запуск
- Код: `src/marketplace_worker/` (Celery-приложение — `celery_app:app`).
- Локально (из корня репо): `uv run celery -A marketplace_worker.celery_app:app worker`.
- Сборка образа из корня репо:
  `docker build -f apps/worker/Dockerfile -t marketplace-worker .`

## Почему отдельный образ
ML-зависимости (~6–8 ГБ) не должны тянуться в каждый деплой тонкого API. Базовый
набор воркера лёгкий (`celery` + `pillow`); тяжёлые слои включаются экстра-группами
из `pyproject.toml` без изменения остального кода:
- `--extra render` — Playwright + Chromium (Этап 3, наложение текста);
- `--extra local` — `torch`/`torchvision` (Этап 6, локальные модели, нужен GPU).

# apps/api — Backend API (тонкий образ)

FastAPI-приложение (Python 3.12). **Тонкий образ** без `torch`/`CUDA`: принимает
запросы менеджера, ведёт CRUD по проектам/товарам/карточкам, ставит задачи в очередь
(Celery + Redis) и отдаёт прогресс через SSE.

> `pyproject.toml` (пакет `marketplace-api` в uv-воркспейсе) и `Dockerfile` уже на месте.
> Каркас Этапа 0 готов: конфиг `config.py` (pydantic-settings), CORS, роутеры под
> префиксом `/api` (`config.py`, `routers/`) + liveness `GET /healthz`. Бизнес-роутеры
> раздела 6, SSE и CRUD добавляются на Этапах 1–5.

## Назначение
- REST API (см. раздел 6 плана) + SSE-поток прогресса генерации.
- Не выполняет тяжёлую генерацию — только оркестрация через очередь.

## Структура и запуск
- Код: `src/marketplace_api/` (пакет `marketplace_api`, точка входа — `main:app`).
- Локально (из корня репо): `uv run uvicorn marketplace_api.main:app --reload`.
- Образ — **тонкий** (без `torch`/`CUDA`). Сборка из корня репо:
  `docker build -f apps/api/Dockerfile -t marketplace-api .`
  (контекст — корень: нужны корневой `uv.lock` и `packages/shared`).

## Связанные сервисы (docker-compose)
- `postgres` — метаданные.
- `redis` — брокер/бэкенд Celery.
- `minio` — хранилище изображений (S3 API).

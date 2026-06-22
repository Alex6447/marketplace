# packages/shared — общий код (контракты и абстракции)

Код, разделяемый между `apps/api` и `apps/worker`:

- **Pydantic-схемы** — единый контракт для вывода LLM, API и БД (источник правды для
  `concept_json`, см. раздел 5 плана).
- **Провайдер-абстракции** `LLMProvider` / `ImageProvider` — переключение hosted ⇄ local
  без правки пайплайна (раздел 4.1 плана).

> `pyproject.toml` (пакет `marketplace-shared` в uv-воркспейсе) на месте; пакет
> подключён зависимостью к `api` и `worker`. Содержимым (схемы, абстракции)
> наполняется на пунктах Этапа 0 «Абстракции LLMProvider / ImageProvider» и далее
> ([docs/plan.md](../../docs/plan.md), раздел 7). Сейчас — только версия пакета.

## Структура
- Код: `src/marketplace_shared/` (пакет `marketplace_shared`).

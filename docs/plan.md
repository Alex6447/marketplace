# План разработки: AI-система генерации карточек товара для маркетплейсов

> Базируется на [docs/idea.md](idea.md). Документ описывает архитектуру, технологический стек, пайплайн генерации, модель данных и поэтапный план работ от MVP до production.

---

## 1. Цели и границы

### Что делаем
Серверная система, которая по данным о товаре генерирует комплект визуальных карточек для маркетплейсов (Ozon, Wildberries, Яндекс Маркет) с итеративной правкой через текстовую обратную связь менеджера.

### Ключевая ценность (и главный риск)
**Сохранение товара без искажений** (форма, цвет, детали, логотип, пропорции). Это — основная техническая сложность и критерий успеха. Всё остальное (UI, очереди, БД) — стандартная инженерия.

### Принципы
- Текст на карточку накладывается **отдельным детерминированным этапом** (графический движок + шаблоны), а не нейросетью — это даёт читаемость, точность и попадание в требования маркетплейсов.
- Товар берётся с **реального фото** и сохраняется через editing-модели / композитинг / inpainting, а не «рисуется заново».
- Пайплайн — это набор изолированных, перезапускаемых стадий с сохранением артефактов на каждом шаге.
- **Провайдеро-независимость:** image- и LLM-генерация скрыты за абстракциями, что даёт работу как на внешних API, так и на **локальных моделях** (закрытый контур) без переписывания кода.

---

## 2. Целевая архитектура

```mermaid
flowchart TB
    FE["🖥️ Frontend<br/>React + TypeScript"]
    API["⚙️ Backend API<br/>FastAPI (тонкий образ)"]
    Q["📨 Очередь задач<br/>Redis + Celery"]
    DB[("🗄️ PostgreSQL<br/>метаданные")]
    S3[("🖼️ MinIO / S3<br/>изображения")]

    subgraph Workers["👷 GPU/CPU Workers (тяжёлый образ)"]
        W1["LLM — идеи / концепции"]
        W2["Image generation"]
        W3["Наложение текста (Playwright)"]
        W4["QA checks"]
    end

    subgraph Providers["🔌 Провайдер-абстракция (hosted ⇄ local)"]
        direction LR
        LP["LLMProvider<br/><small>Claude API · локальный (vLLM/Ollama)</small>"]
        IP["ImageProvider<br/><small>Gemini/Flux API · локальный ComfyUI</small>"]
    end

    LOCAL["🖧 Локальные модели<br/>ComfyUI · Flux/Qwen-Edit · SDXL<br/>BiRefNet/SAM2 · vLLM"]

    FE <-->|"REST + SSE"| API
    API --> Q
    Q --> Workers
    API <--> DB
    Workers <--> DB
    Workers <--> S3
    API <--> S3
    Workers --> Providers
    Providers -.->|"local mode"| LOCAL
    Providers -.->|"hosted mode"| EXT["☁️ Внешние API<br/>Claude · Gemini · Flux"]

    classDef store fill:#1f2937,stroke:#60a5fa,color:#e5e7eb;
    classDef svc fill:#111827,stroke:#34d399,color:#e5e7eb;
    classDef prov fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb;
    class DB,S3 store;
    class FE,API,Q svc;
    class LP,IP,LOCAL,EXT prov;
```

### Компоненты
| Слой | Технология | Обоснование |
|------|-----------|-------------|
| Frontend | React + TypeScript + Vite | Внутренний SPA-дашборд (нет SEO/публичных страниц → SSR Next.js не нужен); статика раздаётся nginx без отдельного Node-сервера; API уже на FastAPI |
| Frontend (доп.) | TanStack Query + shadcn/ui | Управление серверным состоянием/кэшем запросов; готовый UI-кит ускоряет сборку дашборда |
| Backend API | Python 3.12 + FastAPI (тонкий образ) | Async, экосистема ML, удобно для пайплайнов. 3.12 — компромисс со зрелостью ML-стека. Образ без torch/CUDA — быстрый деплой |
| GPU/CPU Worker | Python 3.12 (тяжёлый образ) | Отдельный образ с torch/CUDA/ComfyUI-клиентом. Разделение зависимостей от API: ML-образ ~6–8 ГБ не тянется в каждый деплой API |
| Очередь | Redis + Celery | Многостадийный пайплайн: `chain`/`group`/`chord`, retry, routing ложатся на DAG почти 1:1. Альтернатива — ARQ (async-native) |
| БД | PostgreSQL | Проекты, товары, карточки, версии, фидбэк |
| Хранилище файлов | MinIO (S3 API) | Локально на сервере заказчика, S3-совместимо |
| LLM | `LLMProvider`: Claude API ⇄ локальный (vLLM/Ollama) | Генерация идей и структурированных концепций. Провайдер переключаем: облако или локальная модель (Qwen2.5-VL и т.п.) в закрытом контуре |
| Image generation | `ImageProvider`: Gemini/Flux API ⇄ локальный ComfyUI | Editing-модели + композитинг, см. раздел 4. Переключение hosted ⇄ local без переписывания пайплайна |
| Наложение текста | HTML/CSS-шаблоны + Playwright (headless Chromium) | Дизайнер авторит шаблоны привычными веб-средствами; сложная инфографика/типографика. Pillow — fallback для тривиальных подписей |
| Прогресс в UI | Server-Sent Events (SSE) | Однонаправленный поток сервер→клиент проще WS, легче за nginx, авто-reconnect |
| Наблюдаемость | Langfuse / OpenTelemetry | Трейсинг и учёт стоимости LLM/генерации на проект и карточку (риск «дорогая генерация») |
| Структурные контракты | Pydantic + tool-use/JSON-schema | Единый контракт для вывода LLM, API и БД — один источник правды для `concept_json` |
| Тулинг | uv + ruff (Python), pnpm (front) | Скорость установки/линтинга и воспроизводимость окружения |
| Контейнеризация | Docker + docker-compose | Воспроизводимое размещение на сервере заказчика |

---

## 3. Пайплайн генерации (ядро системы)

Стадии оформлены как независимые шаги; артефакт каждой стадии сохраняется и доступен для перезапуска/правки.

```mermaid
flowchart TD
    S1["1 · Intake<br/><small>нормализация входных данных, подготовка фото</small>"]
    S2["2 · Idea gen 🤖<br/><small>LLM: слайды, смыслы, акценты, стиль, тексты</small>"]
    S3["3 · Concept gen 🤖<br/><small>LLM: визуальная концепция карточки (JSON)</small>"]
    S4["4 · Asset prep<br/><small>удаление фона, маска товара</small>"]
    S5["5 · Image gen 🎨<br/><small>фон/сцена с сохранением товара</small>"]
    S6["6 · Text overlay 🔤<br/><small>детерминированное наложение текста</small>"]
    S7["7 · QA checks ✅<br/><small>товар на месте, читаемость, размеры МП</small>"]
    S8["8 · Review 👤<br/><small>менеджер смотрит, даёт фидбэк текстом</small>"]
    S9["9 · Feedback loop ↩️<br/><small>парсинг фидбэка → правка стадии → новая версия</small>"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8 --> S9
    S9 -.->|"перегенерировать только нужную стадию"| S3
    S9 -.-> S5
    S9 -.-> S6

    classDef llm fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb;
    classDef img fill:#0f2e2a,stroke:#34d399,color:#e5e7eb;
    classDef human fill:#3b2417,stroke:#fbbf24,color:#e5e7eb;
    class S2,S3 llm;
    class S5,S6,S7 img;
    class S8 human;
```

### Детализация стадий

**[2] Генерация идей (LLM)**
- Вход: характеристики, преимущества, ЦА, стиль бренда, примеры.
- Выход (structured JSON): список слайдов с ролью (обложка/преимущества/сценарий использования/состав/гарантии…), ключевыми смыслами, акцентами, тоном.

**[3] Визуальная концепция (LLM)**
- Для каждой карточки JSON-схема: композиция, позиция товара, фон, инфографика, текстовые блоки (текст + позиция + роль), иконки, цветовая палитра, «что должно быть / чего быть не должно».
- Этот JSON — единый контракт между LLM и движком наложения текста.

**[5] Генерация изображения — стратегия сохранения товара (КРИТИЧНО)**
Подход по убыванию надёжности сохранения:
1. **Editing-модель по инструкции** (основной режим): Flux.1 Kontext / Gemini 2.5 Flash Image / Qwen-Image-Edit — «оставь товар, измени фон/сцену» с reference. Проще и качественнее ручных графов.
2. **Композитинг** (gold standard): вырезаем товар (BiRefNet/SAM2), генерим только фон/сцену, вставляем товар обратно с тенями/refinement. Товар = 1:1 пиксели оригинала.
3. **Inpainting с маской товара**: маскируем товар, перегенерируем только окружение.
4. **ControlNet (canny/depth) + IP-Adapter**: когда нужна более «врощенная» сцена с жёстким контролем контуров.
5. **img2img с низким denoise** — только как fallback.
- LoRA — опционально на этапе production для повторяющихся товаров/бренд-стиля.
- Реализация через `ImageProvider`: hosted-API (Gemini/Flux) или локальный **ComfyUI** (Flux/Qwen-Edit/SDXL) — режим выбирается конфигом (см. раздел 4.1).

**[6] Наложение текста (отдельный движок)**
- Шаблоны под форматы маркетплейсов (Ozon/WB/ЯМ: размеры, safe-zones, лимиты текста).
- Движок: Pillow/Skia для простого, либо headless Chromium + HTML/CSS для сложной типографики и инфографики.
- Берёт текстовые блоки из JSON концепции (стадия 3) → рендерит поверх изображения.

**[7] QA-проверки (автоматические)**
- Товар присутствует и не искажён (сравнение эмбеддингов/SSIM по региону товара).
- Текст читаем (контраст, минимальный кегль).
- Размеры/соотношение сторон под требования МП.
- Нет «запрещённых» элементов из концепции.

**[9] Цикл обратной связи**
- LLM-классификатор разбирает свободный фидбэк («фон светлее», «текст мельче», «товар исказился») → определяет, какую стадию перезапустить и с какими дельта-параметрами.
- Перегенерируется только нужная стадия → копится история версий.

---

## 4. Выбор инструментов генерации изображений

Подход к сохранению товара строится на **современных instruction-based editing-моделях** (2025–2026), а не на ручных ControlNet-графах 2023 года. Это напрямую снижает главный риск проекта и упрощает пайплайн.

| Задача | Инструмент | Примечание |
|--------|-----------|------------|
| Удаление фона / маска | BiRefNet, RMBG-2.0, SAM2 | BiRefNet — SOTA по краям (волосы, стекло, упаковка). Локально, бесплатно |
| Сохранение товара (основной режим) | Editing-модель: Flux.1 Kontext / Gemini 2.5 Flash Image / Qwen-Image-Edit | «Оставь товар, измени фон/сцену» по инструкции + reference. Сильно проще ControlNet |
| Сохранение товара (gold standard) | Композитинг: вырез товара → генерация фона → вставка с тенями/refine | Товар = 1:1 пиксели оригинала. Когда нужна абсолютная точность |
| Сохранение товара (продвинутый) | ComfyUI: inpaint + ControlNet/IP-Adapter | Для «врощенной» сцены с жёстким контролем контуров |
| Генерация фона/сцены | Flux / SDXL (ComfyUI) или внешний API | Локально для контроля и цены |
| Upscale/refine | Real-ESRGAN, SUPIR | Финальное качество |
| Наложение текста | HTML/CSS + Playwright (Pillow — fallback) | Детерминированно, не нейросеть |

> Решение провайдеро-независимо: абстракции `ImageProvider` и `LLMProvider` позволяют переключать локальные модели и внешние API без переписывания пайплайна.

### 4.1. Режимы развёртывания (hosted / local / hybrid)

Один и тот же пайплайн работает в трёх режимах — выбор делается конфигом провайдеров, без изменения кода:

| Режим | Image / LLM | Когда выбирать | Плюсы / минусы |
|-------|-------------|----------------|----------------|
| **Hosted** | Gemini/Flux API + Claude API | Старт MVP, нет GPU на сервере | + Быстро к результату, ноль ML-ops, не нужен GPU.<br/>− Плата за вызов, данные уходят во внешний API |
| **Local** | ComfyUI (Flux/Qwen-Edit/SDXL) + локальный LLM (vLLM/Ollama, Qwen2.5-VL) | Закрытый контур, чувствительные бренд-данные, большой объём | + Приватность, ноль платы за генерацию, нет зависимости от внешних сервисов.<br/>− Нужен GPU (≥24 ГБ VRAM желательно), ML-ops, ниже потолок качества части моделей |
| **Hybrid** | Локальные модели + внешний API как fallback/для пиковой нагрузки | Прод после обкатки | Баланс цены, приватности и качества |

**Поддержка локальных моделей — обязательное требование архитектуры:**
- Все провайдеры реализуют единый интерфейс; локальный и hosted backend взаимозаменяемы.
- Локальные веса (BiRefNet, SAM2, Flux/Qwen-Edit, SDXL, LLM) монтируются как том и кэшируются; версии моделей фиксируются.
- Локальный LLM (через **vLLM** или **Ollama**) обслуживает стадии идей/концепций и парсинг фидбэка в офлайне.
- Конфигурация провайдеров — на уровне проекта/окружения (можно разные режимы для разных клиентов на одном сервере).

---

## 5. Модель данных (черновик)

```mermaid
erDiagram
    Project ||--o{ Product : "содержит"
    Project ||--o{ CardSet : "содержит"
    Product ||--o{ ProductAsset : "фото / референсы"
    CardSet ||--o{ Card : "карточки"
    Card ||--o{ CardVersion : "версии"
    CardVersion ||--o{ Feedback : "правки"

    Project {
        uuid id PK
        string name
        string brand_style
        datetime created_at
    }
    Product {
        uuid id PK
        uuid project_id FK
        string title
        json attributes_json
        text advantages
        string target_audience
        json requirements_json
    }
    ProductAsset {
        uuid id PK
        uuid product_id FK
        string type "photo | reference"
        string s3_key
        string mask_s3_key
    }
    CardSet {
        uuid id PK
        uuid project_id FK
        string status
    }
    Card {
        uuid id PK
        uuid card_set_id FK
        string role
        json concept_json
        int order
    }
    CardVersion {
        uuid id PK
        uuid card_id FK
        int version_no
        string image_s3_key
        string final_s3_key
        json gen_params_json
        json qa_report_json
        datetime created_at
    }
    Feedback {
        uuid id PK
        uuid card_version_id FK
        text text
        json parsed_action_json
        datetime created_at
    }
```

> Отдельно — служебная таблица `Job (id, type, status, payload_json, result_json, error)` для отслеживания фоновых задач генерации.

---

## 6. API (ключевые эндпоинты)

```
POST   /projects                       создать проект
POST   /projects/{id}/products         загрузить товар (фото + описание)
POST   /products/{id}/ideas            запустить генерацию идей  → job
GET    /products/{id}/ideas            получить идеи
POST   /products/{id}/cards            сгенерировать концепции карточек → job
POST   /cards/{id}/generate            генерация изображения + текст → job
POST   /card-versions/{id}/feedback    текстовый фидбэк → новая версия (job)
GET    /jobs/{id}                      статус задачи
GET    /card-versions/{id}/download    скачать готовый вариант
GET    /jobs/{id}/events               прогресс генерации (SSE-поток)
```

---

## 7. Поэтапный план работ

> **Стратегия:** идём **API-first** — MVP собираем на hosted-моделях (без GPU, без ML-ops, быстрее к результату), затем подключаем локальные модели через те же провайдер-абстракции (Этап 6). Если GPU есть с самого начала — Этап 6 можно вести параллельно.

### Этап 0 — Подготовка (1 неделя)
- [x] Репозиторий (monorepo), структура, docker-compose (api, worker, postgres, redis, minio). _<!-- структура apps/{api,worker,frontend} + packages/shared; docker-compose.yml: postgres/redis/minio (+ minio-init бакета) рабочие и проверены, api/worker под профилем `app` (их Dockerfile — следующий пункт) -->_
- [x] Разделение образов: тонкий API и тяжёлый worker; тулинг uv/ruff/pnpm. _<!-- uv-воркспейс (apps/api, apps/worker, packages/shared) + общий ruff; два Dockerfile (тонкий API без torch / тяжёлый worker, ML/Playwright — опц. extra render/local); pnpm-воркспейс для apps/frontend. Образы собираются из корня репо, api проверен (/healthz → 200). Полный каркас app — следующий пункт -->_
- [x] Каркас FastAPI + React (TanStack Query, shadcn/ui), базовый CI, линтеры. _<!-- FastAPI-каркас (config.py на pydantic-settings, CORS, роутеры под /api + /healthz; ruff check/format чисто, OpenAPI отдаёт /api/health и /healthz). Каркас фронта apps/frontend (Vite+React18+TS, TanStack Query, shadcn/ui: Tailwind/CSS-переменные/Button, демо-запрос /api/health) + линтеры (ESLint flat + Prettier) + CI .github/workflows/ci.yml (python: uv+ruff; frontend: pnpm+eslint+prettier+tsc/build). `pnpm install` выполнен → корневой pnpm-lock.yaml перегенерирован (2.6k строк), `pnpm install --frozen-lockfile` проходит. Проверено: eslint (0 ошибок, 1 warning react-refresh на shadcn button — не блокирует), prettier --check чисто, tsc -b чисто, vite build успешен -->_
- [x] Абстракции `LLMProvider` / `ImageProvider` (интерфейс + hosted-реализации). _<!-- пакет marketplace_shared.providers: contracts.py (Pydantic-контракты LLM/Image + Usage), base.py (ABC LLMProvider.complete, ImageProvider.edit/generate, async), config.py (ProviderSettings на pydantic-settings + .env_example), echo.py (офлайн-провайдеры: EchoLLM детерминированный + болванка по JSON-schema, EchoImage.edit сохраняет товар 1:1), hosted.py (каркасы AnthropicLLMProvider/GeminiImageProvider: конфиг+ключ читаются, методы → ProviderNotImplemented), registry.py (фабрики get_llm_provider/get_image_provider по конфигу), errors.py. Дефолт — echo (без сети/ключей). ruff чисто, smoke-проверки (8 шт.) пройдены. Реальные сетевые вызовы hosted — следующие два пункта (Claude API / editing-API) -->_
- [x] Подключение Claude API + tool-use/JSON-schema, валидация Pydantic. _<!-- AnthropicLLMProvider.complete (providers/hosted.py) на официальном SDK anthropic (async-клиент AsyncAnthropic): structured-вывод по JSON Schema через output_config.format (response_schema → LLMResponse.data, json.loads), адаптивное мышление по умолчанию, модель claude-opus-4-8. Учтены особенности Opus 4.8: temperature/top_p НЕ передаются (иначе 400), budget_tokens не используется. Обработка stop_reason: refusal → ProviderError, max_tokens при structured → ProviderError (неполный JSON). usage (вкл. cache_*) маппится в Usage. Логика вынесена в чистые _build_kwargs/_parse_response — покрыта smoke-тестами (6 шт.) на фейках без сети/ключа. anthropic>=0.69 добавлен в shared (резолв 0.111). ruff чисто. Реальные сетевые вызовы требуют ANTHROPIC_API_KEY и LLM_PROVIDER=anthropic. JSON-контракт стадий [2]/[3] на Pydantic — наполняется в Этапе 1. -->_
- [x] Подключение editing-API (Gemini/Flux) — проверка «сохрани товар, смени фон». _<!-- GeminiImageProvider (providers/hosted.py) на официальном SDK google-genai (async-клиент client.aio), модель gemini-2.5-flash-image. edit (основной режим [5] «оставь товар, измени фон/сцену»: инструкция + входное фото + опц. референсы) и generate (фон с нуля). Вход ImageRef: inline-байты или presigned-URL (MinIO/S3) — url скачиваем сами через httpx, т.к. SDK берёт только Files-API URI. Выход — inline-байты из candidates[0].content.parts[].inline_data → ImageRef(data=...). Блокировки: prompt_feedback.block_reason и finish_reason кандидата → ProviderError; нет картинки → ProviderError. usage_metadata → Usage. Логика в чистых _build_contents/_build_config/_parse_response/_map_gemini_usage — покрыта smoke-тестами (19 шт.) на фейках без сети/ключа; сборка реальных объектов SDK (GenerateContentConfig, Part.from_bytes) проверена. В shared добавлены google-genai>=1.0 и httpx>=0.27 (резолв google-genai 2.9.0). ruff чисто. Реальные сетевые вызовы требуют GEMINI_API_KEY и IMAGE_PROVIDER=gemini. Flux/BFL (bfl_api_key зарезервирован в конфиге) — отдельный провайдер при необходимости; для проверки «сохрани товар, смени фон» достаточно Gemini. -->_

### Этап 1 — Текстовый пайплайн без картинок (1–2 недели)
- [x] Модель данных + миграции. _<!-- ORM-модель в packages/shared/marketplace_shared/db: base.py (DeclarativeBase + naming_convention для стабильных имён ограничений, TimestampMixin, uuid_pk), models.py (8 таблиц раздела 5: projects/products/product_assets/card_sets/cards/card_versions/feedback + служебная jobs; UUID-PK, JSONB, FK c ON DELETE CASCADE, индексы по FK и jobs.status), session.py (async-движок psycopg v3 + async_sessionmaker + get_session-зависимость FastAPI), config.py (DbSettings из DATABASE_URL, подстановка диалекта postgresql+psycopg). Alembic в корне: alembic.ini (url берётся из DATABASE_URL через env.py, post-write hook ruff), migrations/env.py (sync-движок psycopg, target_metadata=Base.metadata, compare_type/server_default), первая миграция migrations/versions/…_initial_schema.py. Применена к dev-БД `marketplace`: upgrade/downgrade-roundtrip ОК, `alembic check` — расхождений нет. ruff чисто. Зависимости shared: sqlalchemy[asyncio]>=2.0, psycopg[binary]>=3.2, alembic>=1.13. NB: async-движок на Windows требует SelectorEventLoop (psycopg+Proactor несовместимы) — учесть при локальном запуске API на Этапе 1; в Docker (Linux) проблемы нет. -->_
- [x] CRUD: проект → товар → загрузка фото/описания. _<!-- API-роутеры (apps/api/.../routers): projects.py (POST/GET список/GET по id), products.py (POST/GET в рамках проекта + GET /products/{id}), assets.py (POST загрузка фото/референса в MinIO + GET список с presigned-URL). DTO в schemas.py (Pydantic, отделены от ORM, from_attributes). Эндпоинты под /api: POST|GET /projects, GET /projects/{id}, POST|GET /projects/{id}/products, GET /products/{id}, POST|GET /products/{id}/assets. Хранилище — новый модуль marketplace_shared.storage (config.py: StorageSettings из S3_* env; s3.py: S3Storage на boto3 — put_object/presigned_get_url/ensure_bucket/delete_object, path-style для MinIO, singleton get_storage). Boto3-вызовы в async-эндпоинтах обёрнуты в run_in_threadpool. Загрузка через multipart (python-multipart), лимит 20 МБ, ключ products/{product_id}/assets/{asset_id}<ext>; изображение в БД не хранится. На Windows в main.py выставлена WindowsSelectorEventLoopPolicy (psycopg async несовместим с ProactorEventLoop; на Linux/Docker — no-op). Зависимости: boto3>=1.34 (shared), python-multipart>=0.0.9 (api). .env_example: добавлен S3_REGION. Проверено: ruff чисто, OpenAPI отдаёт все 6 эндпоинтов, ASGI-smoke на отдельной БД marketplace_test (CRUD + загрузка ассета с фейк-хранилищем, 404/400) — все проверки прошли. NB: реальная загрузка в MinIO требует поднятого docker-compose (minio был выключен при проверке). -->_
- [x] Стадия [2] генерация идей (LLM). _<!-- Провайдеро-независимая логика стадии — пакет marketplace_shared.pipeline (ideas.py): Pydantic-контракты ProductBrief (вход: характеристики/преимущества/ЦА/требования + стиль бренда из проекта) и ProductIdeas/IdeaSlide (выход: слайды с ролью/смыслами/акцентами/тоном) — они же единый источник JSON Schema (IDEAS_RESPONSE_SCHEMA = ProductIdeas.model_json_schema()) для structured-вывода LLM и валидации ответа; build_ideas_request (чистая, RU system-промт арт-директора + рекомендованные роли) и generate_ideas(provider, brief) (вызов LLMProvider.complete, валидация, ProviderError если нет structured-data). Хранение — новое nullable-поле products.ideas_json (JSONB) + миграция a10c0af96e25 (применена к dev-БД, alembic check чисто). API-роутер apps/api/.../routers/ideas.py: POST /products/{id}/ideas (синхронно на Этапе 1, без Celery; идемпотентно — 409 при повторе без force, force=true перетирает; 404 нет товара; 502 ProviderError) и GET /products/{id}/ideas (404 пока не сгенерировано); DTO IdeasGenerateRequest/IdeasRead. echo-стаб (_stub_from_schema) научён резолвить $ref/$defs — офлайн-дефолт даёт валидный ProductIdeas. ruff чисто. Проверено: smoke пайплайна на echo + ProviderError-кейс; end-to-end ASGI на отдельной БД marketplace_test (проект→товар→idea: 201/404/409/force/200). Постановка в очередь + job/SSE («→ job» из раздела 6) — Этап 2. -->_
- [x] Стадия [3] визуальные концепции (LLM, JSON-контракт). _<!-- Провайдеро-независимая логика — пакет marketplace_shared.pipeline (concepts.py): Pydantic-контракты TextBlock (текст+роль+позиция для движка текста [6]), CardConcept (композиция, позиция товара, фон, инфографика, текстовые блоки, иконки, палитра, must_have/must_not_have) и CardSetConcepts — они же единый источник JSON Schema (CONCEPTS_RESPONSE_SCHEMA) для structured-вывода LLM и валидации; build_concepts_request (чистая, RU system-промт арт-директора, в must_not_have закладывает запрет на искажение товара) и generate_concepts(provider, brief, ideas) — вход = бриф товара + идеи стадии [2]. Хранение — CardSet (+ карточки Card.concept_json), к CardSet добавлено nullable product_id (FK→products, ON DELETE CASCADE, индекс) + миграция fddc5f32557b (применена к dev-БД, alembic check чисто). API-роутер apps/api/.../routers/cards.py: POST /products/{id}/cards (синхронно на Этапе 1, без Celery; требует идей → 409 если ideas_json пуст; идемпотентно — 409 при повторе, force=true удаляет прежние наборы товара и генерирует заново; 404 нет товара; 502 ProviderError) и GET /products/{id}/cards (последний набор; 404 если нет). DTO ConceptsGenerateRequest/CardRead (concept ← concept_json)/CardSetRead. ruff чисто. Проверено: smoke пайплайна на echo (схема/$defs, build_request, generate, ProviderError) + end-to-end ASGI на marketplace_test (проект→товар→идеи→концепции: 409-без-идей/404/201/409-повтор/force/404). Постановка в очередь + job/SSE («→ job» из раздела 6) — Этап 2. -->_
- [ ] UI: создание проекта, ввод данных, просмотр идей и концепций. _<!-- ⚠️ ПРИ РАЗРАБОТКЕ ПОЛНОЦЕННОГО UI: обязательно применить скилл `frontend-design` (не лепить дефолтный shadcn-каркас как сейчас). Сразу заложить две темы — тёмную (по умолчанию) и светлую — с переключателем; CSS-переменные тем уже подготовлены в каркасе. Требование распространяется на весь UI проекта, включая Этап 4. -->_

### Этап 2 — Генерация изображений с сохранением товара (2–3 недели) ⭐ ключевой риск
- [ ] Стадия [5] основной режим: editing-модель (Flux Kontext / Gemini) через `ImageProvider`.
- [ ] Стадия [4] удаление фона + маска (BiRefNet/SAM2).
- [ ] Стадия [5] композитинг товара на сгенерированный фон (gold standard).
- [ ] Очередь Celery (`chain`/`group`) + worker'ы, SSE-прогресс.
- [ ] Контент-адресуемый кэш артефактов стадий (для «правка только нужной стадии»).
- [ ] Сравнение подходов на реальных товарах заказчика, выбор дефолта.

### Этап 3 — Наложение текста и инфографики (1–2 недели)
- [ ] Движок рендера: HTML/CSS-шаблоны + Playwright (Pillow — fallback).
- [ ] Шаблоны под Ozon / WB / Яндекс Маркет (размеры, safe-zones).
- [ ] Рендер текстовых блоков из JSON концепции поверх изображения.

### Этап 4 — Цикл обратной связи (1–2 недели)
- [ ] LLM-парсер свободного фидбэка → действие + стадия + дельта-параметры.
- [ ] Перегенерация нужной стадии, история версий.
- [ ] UI: просмотр версий, ввод фидбэка, сравнение вариантов.

### Этап 5 — QA, экспорт, полировка (1–2 недели)
- [ ] Авто-QA (товар на месте, читаемость, размеры).
- [ ] Скачивание/экспорт комплекта (zip, под форматы МП).
- [ ] Обработка ошибок, ретраи, логирование, наблюдаемость (Langfuse/OTel + учёт стоимости).

**Итог MVP** покрывает все 9 пунктов раздела «Что хотим получить» из [idea.md](idea.md): проект → загрузка → идеи → концепции → изображения → текст → фидбэк → новая версия → скачивание.

### Этап 6 — Локальные модели / закрытый контур (2–3 недели)
> Включается, когда нужны приватность, снижение цены за генерацию или офлайн-работа. Требует GPU.
- [ ] Локальная реализация `ImageProvider`: ComfyUI (Flux/Qwen-Image-Edit/SDXL), BiRefNet/SAM2.
- [ ] Локальная реализация `LLMProvider`: vLLM/Ollama (напр. Qwen2.5-VL) для идей/концепций/фидбэка.
- [ ] Монтирование и версионирование весов моделей (том + кэш).
- [ ] Конфиг режима (hosted / local / hybrid) на уровне окружения/проекта.
- [ ] Сравнение качества/скорости local vs hosted на товарах заказчика.

### Этап 7 — Размещение на сервере заказчика
- [ ] docker-compose / деплой (профили с/без GPU), бэкапы БД и MinIO.
- [ ] Документация для менеджеров.
- [ ] Нагрузочная проверка очередей.

---

## 8. Риски и митигации

| Риск | Влияние | Митигация |
|------|---------|-----------|
| Нейросеть искажает товар | Критично | Editing-модель + композитинг (товар = реальные пиксели) как gold standard, inpaint/ControlNet как продвинутый режим, авто-QA сравнением |
| Текст нейросетью нечитаем/кривой | Высокое | Текст накладывается отдельным детерминированным движком (HTML/CSS + Playwright) по шаблонам |
| Нет GPU на сервере | Высокое | API-first MVP на hosted-моделях; локальные модели — отдельный включаемый этап |
| Долгая/дорогая генерация | Среднее | Кэш стадий, перегенерация только изменённой стадии, переход на локальные модели, учёт стоимости (Langfuse) |
| Утечка чувствительных бренд-данных | Среднее | Режим local: всё в закрытом контуре на локальных моделях, без внешних API |
| Фидбэк понят неверно | Среднее | LLM-классификатор + предпросмотр действия перед перегенерацией |
| Несоответствие требованиям МП | Среднее | Шаблоны с зашитыми размерами/safe-zones + QA-проверка |
| Привязка к одному провайдеру | Низкое | Абстракции `ImageProvider` / `LLMProvider`, переключаемые бэкенды (hosted ⇄ local) |

---

## 9. Открытые вопросы к заказчику

1. Доступный сервер: есть ли GPU (модель/VRAM)? От этого зависит, когда подключать локальные модели (Этап 6).
2. Приоритет режима: hosted (быстрее и дешевле на старте) или local/закрытый контур (приватность бренд-данных) важнее с самого начала?
3. Объём: сколько товаров/карточек в день ожидается (для масштабирования очередей)?
4. Брендбук/шаблоны: есть ли фиксированные требования по шрифтам, цветам, лого?
5. Языки карточек (только RU?) и целевые маркетплейсы в приоритете.
6. Бюджет на внешние API генерации (для hosted-режима, пока/если нет локальных мощностей).
7. Нужна ли мультипользовательность / роли / авторизация в MVP.

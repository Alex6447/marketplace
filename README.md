<div align="center">

# 🛍️ AI Marketplace Cards

### AI-система генерации визуальных карточек товара для маркетплейсов

Превращает фото и описание товара в готовый комплект продающих карточек для **Ozon**, **Wildberries** и **Яндекс Маркета** — с сохранением товара без искажений и итеративной правкой обычным текстом.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-TS-61DAFB?logo=react&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Redis-37814A?logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)
![Status](https://img.shields.io/badge/status-🚧%20в%20разработке-orange)

> 🚧 **Проект в активной разработке.** README описывает целевой продукт; часть функциональности и команд из раздела «Быстрый старт» появится по мере реализации (см. план в [docs_marketplace/plan.md](docs_marketplace/plan.md)).

</div>

---

## ✨ Возможности

- 🖼️ **Сохранение товара без искажений** — форма, цвет, детали, логотип и пропорции остаются как на оригинальном фото (editing-модели + композитинг).
- 💡 **Генерация идей карточек** — LLM предлагает набор слайдов, смыслы, акценты и визуальный стиль под товар и целевую аудиторию.
- 🎨 **Детальная визуальная концепция** каждой карточки: композиция, фон, инфографика, текстовые блоки, иконки, палитра.
- 🔤 **Чёткое наложение текста** отдельным графическим движком (HTML/CSS + Playwright), а не нейросетью — текст всегда читаем и соответствует правилам маркетплейсов.
- 💬 **Правки обычным текстом** — «сделай фон светлее», «текст крупнее», «убери лишнее»: система понимает фидбэк и перегенерирует только нужную стадию.
- 🕓 **История версий** каждой карточки и сравнение вариантов.
- 🔌 **Hosted ⇄ Local** — работает как на внешних API, так и полностью на локальных моделях в закрытом контуре.
- 📦 **Экспорт** готового комплекта под форматы маркетплейсов.

---

## 🏗️ Архитектура

```mermaid
flowchart TB
    FE["🖥️ Frontend<br/>React + TypeScript"]
    API["⚙️ Backend API<br/>FastAPI"]
    Q["📨 Очередь задач<br/>Redis + Celery"]
    DB[("🗄️ PostgreSQL")]
    S3[("🖼️ MinIO / S3")]

    subgraph Workers["👷 Workers"]
        W1["LLM — идеи / концепции"]
        W2["Image generation"]
        W3["Text overlay (Playwright)"]
        W4["QA checks"]
    end

    subgraph Providers["🔌 Провайдер-абстракция"]
        LP["LLMProvider"]
        IP["ImageProvider"]
    end

    FE <-->|"REST + SSE"| API
    API --> Q --> Workers
    API <--> DB
    Workers <--> DB
    Workers <--> S3
    API <--> S3
    Workers --> Providers
    Providers -.->|local| LOCAL["🖧 Локальные модели<br/>ComfyUI · Flux/Qwen-Edit · vLLM"]
    Providers -.->|hosted| EXT["☁️ Внешние API<br/>Claude · Gemini · Flux"]

    classDef store fill:#1f2937,stroke:#60a5fa,color:#e5e7eb;
    classDef svc fill:#111827,stroke:#34d399,color:#e5e7eb;
    classDef prov fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb;
    class DB,S3 store;
    class FE,API,Q svc;
    class LP,IP,LOCAL,EXT prov;
```

---

## 🔄 Как это работает

```mermaid
flowchart LR
    S1["1 · Данные<br/>о товаре"] --> S2["2 · Идеи 🤖"] --> S3["3 · Концепция 🤖"]
    S3 --> S5["4 · Генерация 🎨"] --> S6["5 · Текст 🔤"] --> S7["6 · QA ✅"]
    S7 --> S8["7 · Ревью 👤"] --> S9["8 · Фидбэк ↩️"]
    S9 -.->|"правка только нужной стадии"| S3
    S9 -.-> S5
    S9 -.-> S6

    classDef llm fill:#1e1b4b,stroke:#818cf8,color:#e5e7eb;
    classDef img fill:#0f2e2a,stroke:#34d399,color:#e5e7eb;
    classDef human fill:#3b2417,stroke:#fbbf24,color:#e5e7eb;
    class S2,S3 llm;
    class S5,S6,S7 img;
    class S8 human;
```

1. **Менеджер** загружает фото и описание товара, указывает стиль бренда и требования.
2. **LLM** генерирует идеи карточек, затем детальную визуальную концепцию каждой.
3. **Генератор изображений** создаёт фон/сцену, сохраняя товар (editing-модель или композитинг).
4. **Движок текста** накладывает тексты и инфографику по шаблонам маркетплейсов.
5. **Авто-QA** проверяет: товар на месте, текст читаем, размеры верны.
6. **Менеджер** смотрит результат и правит обычным текстом → система перегенерирует только нужную стадию.

---

## 🧰 Технологический стек

| Слой | Технологии |
|------|-----------|
| **Backend** | Python 3.12, FastAPI, Celery, Redis |
| **Frontend** | React, TypeScript, Vite, TanStack Query, shadcn/ui |
| **Хранилища** | PostgreSQL (метаданные), MinIO/S3 (изображения) |
| **AI — LLM** | Claude API ⇄ локальный (vLLM / Ollama) через `LLMProvider` |
| **AI — Image** | Flux.1 Kontext, Gemini 2.5 Flash Image, Qwen-Image-Edit, ComfyUI ⇄ через `ImageProvider` |
| **Сегментация** | BiRefNet, SAM2 |
| **Текст/инфографика** | HTML/CSS + Playwright (Pillow — fallback) |
| **Наблюдаемость** | Langfuse / OpenTelemetry |
| **Инфраструктура** | Docker, docker-compose, uv, ruff, pnpm |

---

## 🚀 Быстрый старт

```bash
# 1. Клонировать репозиторий
git clone <repo-url> && cd marketplace

# 2. Настроить окружение
cp .env_example .env        # заполнить DATABASE_URL и ключи провайдеров

# 3. Поднять инфраструктуру (postgres, redis, minio, api, worker)
docker-compose up -d

# 4. Применить миграции
uv run alembic upgrade head

# 5. Запустить фронтенд
cd frontend && pnpm install && pnpm dev
```

После старта:

- **Веб-интерфейс:** http://localhost:5173
- **API + docs:** http://localhost:8000/docs

### Режимы работы

| Режим | Когда использовать |
|-------|--------------------|
| **Hosted** | Быстрый старт, без GPU — генерация через внешние API |
| **Local** | Закрытый контур, приватность бренд-данных — локальные модели (нужен GPU) |
| **Hybrid** | Баланс цены, качества и приватности |

Режим переключается в `.env` без изменения кода.

---

## 📁 Структура проекта

```
marketplace/
├── backend/            # FastAPI, пайплайн, провайдеры, Celery-воркеры
├── frontend/           # React + TypeScript SPA
├── docs_marketplace/               # idea.md, plan.md — задача и план разработки
├── docker-compose.yml  # api, worker, postgres, redis, minio
├── .env_example        # шаблон переменных окружения
└── README.md
```

---

## 📚 Документация

- [docs_marketplace/idea.md](docs_marketplace/idea.md) — постановка задачи.
- [docs_marketplace/plan.md](docs_marketplace/plan.md) — архитектура, пайплайн, модель данных, поэтапный план.
- [CLAUDE.md](CLAUDE.md) — контекст и соглашения проекта.

---

<div align="center">
<sub>Сделано с ❤️ для тех, кто продаёт на маркетплейсах</sub>
</div>

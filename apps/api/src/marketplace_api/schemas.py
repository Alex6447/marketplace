"""Pydantic-схемы запросов/ответов API (DTO).

Отделены от ORM-моделей (`marketplace_shared.db.models`): ORM — это схема БД,
а DTO — публичный контракт API. `from_attributes=True` позволяет собирать
схему ответа прямо из ORM-объекта.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Project ----------------------------------------------------------------


class ProjectCreate(BaseModel):
    """Тело запроса на создание проекта."""

    name: str = Field(min_length=1, max_length=255)
    brand_style: str | None = None


class ProjectRead(BaseModel):
    """Проект в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    brand_style: str | None
    created_at: datetime


# --- Product ----------------------------------------------------------------


class ProductCreate(BaseModel):
    """Тело запроса на создание товара внутри проекта."""

    title: str = Field(min_length=1, max_length=512)
    attributes_json: dict[str, Any] = Field(default_factory=dict)
    advantages: str | None = None
    target_audience: str | None = Field(default=None, max_length=512)
    requirements_json: dict[str, Any] = Field(default_factory=dict)


class ProductRead(BaseModel):
    """Товар в ответе API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    attributes_json: dict[str, Any]
    advantages: str | None
    target_audience: str | None
    requirements_json: dict[str, Any]


# --- Ideas (стадия [2]) -----------------------------------------------------


class IdeasGenerateRequest(BaseModel):
    """Параметры запуска генерации идей (все опциональны)."""

    #: Переопределить модель LLM (иначе — дефолт выбранного провайдера).
    model: str | None = None
    #: Перегенерировать, даже если идеи уже есть (иначе вернётся 409).
    force: bool = False


class IdeasRead(BaseModel):
    """Идеи комплекта карточек товара (результат стадии [2])."""

    product_id: uuid.UUID
    #: Структура соответствует `marketplace_shared.pipeline.ProductIdeas`.
    ideas: dict[str, Any]


# --- Concepts (стадия [3]) --------------------------------------------------


class ConceptsGenerateRequest(BaseModel):
    """Параметры запуска генерации визуальных концепций (все опциональны)."""

    #: Переопределить модель LLM (иначе — дефолт выбранного провайдера).
    model: str | None = None
    #: Перегенерировать, даже если концепции уже есть (иначе вернётся 409).
    force: bool = False


class CardRead(BaseModel):
    """Карточка набора с визуальной концепцией (результат стадии [3])."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    order: int
    #: Структура соответствует `marketplace_shared.pipeline.CardConcept`.
    concept: dict[str, Any] | None = Field(default=None, validation_alias="concept_json")


class CardSetRead(BaseModel):
    """Набор карточек товара с концепциями (результат стадии [3])."""

    id: uuid.UUID
    product_id: uuid.UUID
    status: str
    cards: list[CardRead]


# --- Card image generation (стадия [5]) -------------------------------------


CardImageMode = Literal["edit", "composite"]


class CardImageGenerateRequest(BaseModel):
    """Параметры запуска генерации изображения карточки (все опциональны)."""

    #: Режим стадии [5]: "edit" — editing-модель (товар сохраняет провайдер),
    #: "composite" — gold standard: фон генерируется, вырез товара (стадия [4])
    #: накладывается 1:1. Композитинг требует построенной маски (стадия [4]).
    mode: CardImageMode = "edit"
    #: Переопределить модель image-провайдера (иначе — дефолт выбранного провайдера).
    model: str | None = None
    #: Seed для воспроизводимости (если провайдер поддерживает).
    seed: int | None = None
    #: Целевой размер, напр. "1024x1024" (если провайдер поддерживает).
    size: str | None = None
    #: Использовать референс-ассеты товара как референсы сцены/стиля.
    use_references: bool = True


class CardSetGenerateRequest(CardImageGenerateRequest):
    """Параметры генерации изображений для всего набора карточек (стадия [5]).

    Наследует поля одиночной генерации; ``prepare`` добавляет перед композитингом
    стадию [4] (маска товара) — тогда каждая карточка идёт цепочкой matting→image.
    """

    #: Сначала построить маску товара (стадия [4]), затем композитинг (chain).
    prepare: bool = False


class JobRead(BaseModel):
    """Фоновая задача генерации (таблица Job) — для статуса и SSE-прогресса."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    status: str
    progress: int
    stage: str | None
    result_json: dict[str, Any] | None
    error: str | None
    created_at: datetime


class CardVersionRead(BaseModel):
    """Версия карточки — результат стадии [5] (изображение до наложения текста)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    card_id: uuid.UUID
    version_no: int
    image_s3_key: str | None
    final_s3_key: str | None
    gen_params_json: dict[str, Any]
    created_at: datetime
    #: Presigned-ссылка на сгенерированное изображение (генерируется на лету).
    image_url: str | None = None
    #: Presigned-ссылка на финал с наложенным текстом (стадия [6]); None, пока нет.
    final_url: str | None = None


class CardTextRenderRequest(BaseModel):
    """Параметры наложения текста на версию карточки — стадия [6]."""

    #: Ключ шаблона маркетплейса (размеры/safe-zone). None → дефолтный шаблон.
    template_key: str | None = None


# --- ProductAsset -----------------------------------------------------------

AssetType = Literal["photo", "reference"]


class ProductAssetRead(BaseModel):
    """Файл товара (фото/референс) в ответе API.

    `url`/`mask_url`/`cutout_url` — presigned-ссылки на скачивание из хранилища
    (живут ограниченное время), генерируются на лету, в БД не хранятся.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    type: str
    s3_key: str
    mask_s3_key: str | None
    url: str | None = None
    #: Presigned-ссылка на маску товара (стадия [4]); None, пока маска не построена.
    mask_url: str | None = None
    #: Presigned-ссылка на вырез с прозрачным фоном (сосед маски по ключу).
    cutout_url: str | None = None


class MaskGenerateRequest(BaseModel):
    """Параметры запуска подготовки ассета — стадия [4] (все опциональны)."""

    #: Переопределить модель matting-провайдера (иначе — дефолт провайдера).
    model: str | None = None
    #: Перестроить маску, даже если она уже есть (иначе вернётся 409).
    force: bool = False

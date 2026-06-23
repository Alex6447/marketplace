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


# --- ProductAsset -----------------------------------------------------------

AssetType = Literal["photo", "reference"]


class ProductAssetRead(BaseModel):
    """Файл товара (фото/референс) в ответе API.

    `url` — presigned-ссылка на скачивание из хранилища (живёт ограниченное время),
    генерируется на лету, в БД не хранится.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    type: str
    s3_key: str
    mask_s3_key: str | None
    url: str | None = None

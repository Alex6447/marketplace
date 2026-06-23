"""ORM-модель данных (docs/plan.md, раздел 5).

Сущности: проект → товары и наборы карточек → карточки → версии → фидбэк.
Плюс служебная таблица :class:`Job` для отслеживания фоновых задач генерации.

JSON-поля хранятся как ``JSONB`` (индексируемый бинарный JSON в PostgreSQL).
Идентификаторы — UUID, генерируются приложением. Каскад ``ON DELETE CASCADE``
на дочерних связях: удаление проекта/товара/карточки уносит зависимые записи.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from marketplace_shared.db.base import Base, TimestampMixin, uuid_pk


class Project(Base, TimestampMixin):
    """Проект — верхнеуровневая единица работы (один бренд/заказ)."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Описание стиля бренда (тон, визуальные правила) — вход стадий идей/концепций.
    brand_style: Mapped[str | None] = mapped_column(Text, nullable=True)

    products: Mapped[list[Product]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
    card_sets: Mapped[list[CardSet]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Product(Base):
    """Товар внутри проекта: характеристики, преимущества, ЦА, требования."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    #: Характеристики товара (произвольная структура из входных данных).
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    advantages: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Требования к карточкам (форматы МП, ограничения) — вход стадий [2]/[3].
    requirements_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Идеи комплекта карточек — результат стадии [2] (план слайдов, смыслы, тон).
    #: NULL, пока идеи не сгенерированы; перезапись стадии заменяет значение целиком.
    ideas_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    project: Mapped[Project] = relationship(back_populates="products")
    assets: Mapped[list[ProductAsset]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )


class ProductAsset(Base):
    """Файл товара: исходное фото или референс. Хранится в MinIO/S3 по ключу."""

    __tablename__ = "product_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: "photo" — фото товара (его сохраняем без искажений), "reference" — референс сцены/стиля.
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    #: Ключ маски товара (стадия [4], BiRefNet/SAM2) — появляется после подготовки ассета.
    mask_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    product: Mapped[Product] = relationship(back_populates="assets")


class CardSet(Base, TimestampMixin):
    """Набор карточек проекта (комплект под маркетплейс)."""

    __tablename__ = "card_sets"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Статус набора (draft/generating/ready/…). Строка — расширяемо без миграций.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    project: Mapped[Project] = relationship(back_populates="card_sets")
    cards: Mapped[list[Card]] = relationship(
        back_populates="card_set",
        cascade="all, delete-orphan",
    )


class Card(Base):
    """Карточка набора: роль (обложка/преимущества/…) и визуальная концепция (JSON)."""

    __tablename__ = "cards"

    id: Mapped[uuid.UUID] = uuid_pk()
    card_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("card_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Роль слайда: обложка / преимущества / сценарий использования / состав / гарантии…
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Визуальная концепция — единый контракт между LLM (стадия [3]) и движком текста [6].
    concept_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Порядок карточки в наборе. Имя колонки "order" — зарезервированное слово,
    #: SQLAlchemy экранирует его автоматически.
    order: Mapped[int] = mapped_column("order", Integer, nullable=False, default=0)

    card_set: Mapped[CardSet] = relationship(back_populates="cards")
    versions: Mapped[list[CardVersion]] = relationship(
        back_populates="card",
        cascade="all, delete-orphan",
    )


class CardVersion(Base, TimestampMixin):
    """Версия карточки: сгенерированное изображение, финал с текстом, отчёт QA."""

    __tablename__ = "card_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Изображение после стадии [5] (фон/сцена с сохранённым товаром), до наложения текста.
    image_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    #: Финальная карточка после наложения текста (стадия [6]).
    final_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    #: Параметры генерации (провайдер, модель, seed, дельты фидбэка) — для воспроизводимости.
    gen_params_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Отчёт авто-QA стадии [7] (товар на месте, читаемость, размеры).
    qa_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    card: Mapped[Card] = relationship(back_populates="versions")
    feedback: Mapped[list[Feedback]] = relationship(
        back_populates="card_version",
        cascade="all, delete-orphan",
    )


class Feedback(Base, TimestampMixin):
    """Текстовый фидбэк менеджера к версии карточки и его разбор LLM (стадия [9])."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    card_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("card_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Результат LLM-парсинга: действие + целевая стадия + дельта-параметры.
    parsed_action_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    card_version: Mapped[CardVersion] = relationship(back_populates="feedback")


class Job(Base, TimestampMixin):
    """Служебная запись фоновой задачи генерации (docs/plan.md, раздел 5)."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Тип задачи (стадия пайплайна: ideas/concepts/generate/feedback…).
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Статус: pending/running/success/failure/retry.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

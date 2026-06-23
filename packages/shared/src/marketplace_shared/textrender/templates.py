"""Шаблоны карточек маркетплейсов: размеры и safe-zones (стадия [6], раздел 6).

Каждый маркетплейс задаёт свои требования к изображению карточки: соотношение
сторон, рекомендованный и минимальный размер, безопасное поле (где нельзя резать
контент), требование белого фона для главного фото, лимит текстовых блоков. Эти
требования зашиты здесь как :class:`MarketplaceTemplate` — единый каталог, из
которого стадия [6] берёт холст и safe-zone для рендера, а стадия [3]/маппинг —
ограничения (следующий пункт Этапа 3).

Значения отражают публичные требования Ozon / Wildberries / Яндекс Маркет на момент
написания (2026); при изменении правил МП правится только этот каталог. Шаблоны —
данные, не код: добавление формата = одна запись в :data:`_TEMPLATES`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import Canvas, SafeZone

#: Поддерживаемые маркетплейсы (RU).
Marketplace = Literal["ozon", "wildberries", "yandex_market"]


class MarketplaceTemplate(BaseModel):
    """Шаблон формата карточки маркетплейса: размеры и безопасное поле."""

    key: str = Field(description="Уникальный ключ шаблона, напр. 'ozon-main'.")
    marketplace: Marketplace
    title: str = Field(description="Человекочитаемое название формата.")
    #: Рекомендованный размер холста (в нём и рендерим).
    canvas: Canvas
    #: Минимально допустимый размер (для валидации входного фото/апскейла).
    min_canvas: Canvas
    aspect_ratio: str = Field(description="Соотношение сторон, напр. '1:1' или '3:4'.")
    safe_zone: SafeZone = Field(default_factory=SafeZone)
    #: Главное фото у ряда МП обязано быть на белом фоне — флаг для стадий генерации/QA.
    white_background_required: bool = False
    #: Рекомендованный лимит текстовых блоков (читаемость; ограничение для маппинга [3]).
    max_text_blocks: int = 6
    notes: str = ""


# Каталог встроенных шаблонов. Числа — публичные требования МП (2026): соотношения
# сторон обязательны, размеры — рекомендованные (МП принимают и больше при том же ratio).
_TEMPLATES: dict[str, MarketplaceTemplate] = {
    "ozon-main": MarketplaceTemplate(
        key="ozon-main",
        marketplace="ozon",
        title="Ozon — главное фото (1:1)",
        canvas=Canvas(width=1000, height=1000),
        min_canvas=Canvas(width=700, height=700),
        aspect_ratio="1:1",
        safe_zone=SafeZone(top=0.06, right=0.06, bottom=0.06, left=0.06),
        white_background_required=True,
        max_text_blocks=4,
        notes="Первое фото — на белом фоне, минимум текста; рич-контент — отдельные карточки.",
    ),
    "ozon-promo": MarketplaceTemplate(
        key="ozon-promo",
        marketplace="ozon",
        title="Ozon — продающая карточка (3:4)",
        canvas=Canvas(width=1080, height=1440),
        min_canvas=Canvas(width=900, height=1200),
        aspect_ratio="3:4",
        safe_zone=SafeZone(top=0.05, right=0.05, bottom=0.05, left=0.05),
        max_text_blocks=6,
        notes="Вертикальный формат под инфографику и преимущества.",
    ),
    "wildberries-main": MarketplaceTemplate(
        key="wildberries-main",
        marketplace="wildberries",
        title="Wildberries — карточка (3:4)",
        canvas=Canvas(width=900, height=1200),
        min_canvas=Canvas(width=700, height=900),
        aspect_ratio="3:4",
        safe_zone=SafeZone(top=0.05, right=0.05, bottom=0.08, left=0.05),
        max_text_blocks=6,
        notes="Вертикаль 3:4; нижняя зона крупнее — под подписи WB в интерфейсе.",
    ),
    "yandex_market-main": MarketplaceTemplate(
        key="yandex_market-main",
        marketplace="yandex_market",
        title="Яндекс Маркет — главное фото (1:1)",
        canvas=Canvas(width=1000, height=1000),
        min_canvas=Canvas(width=600, height=600),
        aspect_ratio="1:1",
        safe_zone=SafeZone(top=0.06, right=0.06, bottom=0.06, left=0.06),
        white_background_required=True,
        max_text_blocks=4,
        notes="Главное фото — на белом фоне без посторонних надписей.",
    ),
}

#: Шаблон по умолчанию, когда формат не указан.
DEFAULT_TEMPLATE_KEY = "ozon-main"


def list_templates() -> list[MarketplaceTemplate]:
    """Все встроенные шаблоны (стабильный порядок по ключу)."""
    return [_TEMPLATES[key] for key in sorted(_TEMPLATES)]


def available_template_keys() -> list[str]:
    """Ключи всех встроенных шаблонов."""
    return sorted(_TEMPLATES)


def templates_for(marketplace: Marketplace) -> list[MarketplaceTemplate]:
    """Шаблоны конкретного маркетплейса."""
    return [t for t in list_templates() if t.marketplace == marketplace]


def get_template(key: str | None = None) -> MarketplaceTemplate:
    """Получить шаблон по ключу (или дефолтный при ``None``).

    Бросает :class:`KeyError` с понятным сообщением, если ключ неизвестен.
    """
    key = key or DEFAULT_TEMPLATE_KEY
    try:
        return _TEMPLATES[key]
    except KeyError:
        raise KeyError(
            f"Неизвестный шаблон {key!r}; доступны: {available_template_keys()}"
        ) from None

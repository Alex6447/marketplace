"""Контракты движка наложения текста (стадия [6], docs/plan.md, разделы 3 и 6).

Текст на карточку наносится **отдельным детерминированным этапом**, а не нейросетью —
это даёт читаемость и точное попадание в требования маркетплейсов. Движок берёт
готовое изображение (результат стадии [5]) и кладёт поверх текстовые блоки.

Контракты здесь — backend-независимые: одни и те же :class:`RenderBlock` рисует и
Playwright (HTML/CSS, основной режим), и Pillow (офлайн-fallback). Маппинг визуальной
концепции (:class:`marketplace_shared.pipeline.concepts.TextBlock`) и шаблонов
маркетплейсов в эти примитивы — отдельные пункты Этапа 3 (см. docs/plan.md, раздел 7).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from marketplace_shared.providers.contracts import ImageRef

#: Позиции блока на карточке — сетка 3×3 (совпадает с RECOMMENDED_POSITIONS стадии [3]).
GridPosition = Literal[
    "top-left",
    "top-center",
    "top-right",
    "middle-left",
    "center",
    "middle-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]

Align = Literal["left", "center", "right"]
Weight = Literal["normal", "bold"]


class RenderBlock(BaseModel):
    """Один текстовый блок для наложения — backend-независимый примитив рендера.

    Размеры/координаты — в пикселях холста (``font_size``) и долях ширины
    (``max_width``), чтобы блок одинаково ложился на холст любого размера.
    """

    text: str = Field(description="Текст блока (как правило, на русском).")
    position: GridPosition = Field(default="center", description="Якорь на сетке 3×3.")
    font_size: int = Field(default=48, gt=0, description="Кегль в пикселях холста.")
    color: str = Field(default="#111111", description="Цвет текста (HEX или имя CSS).")
    weight: Weight = Field(default="normal", description="Насыщенность шрифта.")
    align: Align = Field(default="center", description="Выравнивание строк внутри блока.")
    max_width: float = Field(
        default=0.8,
        gt=0,
        le=1,
        description="Макс. ширина блока в долях ширины холста (перенос строк).",
    )
    background: str | None = Field(
        default=None, description="Цвет подложки-плашки под текстом (например для бейджа)."
    )
    padding: int = Field(default=0, ge=0, description="Отступ подложки вокруг текста, px.")


class Canvas(BaseModel):
    """Размер холста карточки. По умолчанию берётся из базового изображения."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RenderRequest(BaseModel):
    """Запрос на наложение текста поверх изображения карточки.

    ``base_image`` — изображение со стадии [5]. ``blocks`` — что наложить. ``canvas``
    задаёт целевой размер (если отличается от базового — изображение масштабируется).
    ``html`` — необязательный «сырой» HTML-оверлей: им можно полностью переопределить
    раскладку для Playwright (шаблоны Этапа 3); Pillow его игнорирует и рисует blocks.
    """

    base_image: ImageRef
    blocks: list[RenderBlock] = Field(default_factory=list)
    canvas: Canvas | None = None
    html: str | None = None


class RenderResult(BaseModel):
    """Результат наложения: готовое изображение карточки (PNG)."""

    image: ImageRef
    renderer: str
    raw: dict[str, Any] | None = None

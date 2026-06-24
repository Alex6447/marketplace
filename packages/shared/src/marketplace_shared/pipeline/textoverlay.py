"""Стадия [6] — наложение текста концепции на изображение (docs_marketplace/plan.md, разделы 3, 6).

Связывает визуальную концепцию стадии [3] (:class:`CardConcept` с её
``text_blocks``) и движок рендера (:mod:`marketplace_shared.textrender`): переводит
текстовые блоки концепции в backend-независимые :class:`RenderBlock` по шаблону
маркетплейса (размеры, safe-zone, лимит блоков) и отдаёт готовый
:class:`RenderRequest`. Сам рендер выполняет выбранный :class:`TextRenderer`.

Маппинг детерминированный и провайдеро-независимый: роль блока («headline»/«badge»/…)
задаёт кегль (в долях высоты холста), насыщенность, выравнивание и позицию-фолбэк;
позиция берётся из концепции, если она попадает в сетку 3×3, иначе — дефолт роли.
Пункты-преимущества («bullet») объединяются в один маркированный блок — так они не
накладываются друг на друга при простом якорном размещении.
"""

from __future__ import annotations

from typing import get_args

from marketplace_shared.providers.contracts import ImageRef
from marketplace_shared.textrender import (
    Canvas,
    GridPosition,
    MarketplaceTemplate,
    RenderBlock,
    RenderRequest,
    RenderResult,
    TextRenderer,
    get_template,
)

from .concepts import CardConcept, TextBlock

#: Допустимые позиции сетки 3×3 (значения литерала GridPosition).
_GRID_POSITIONS = frozenset(get_args(GridPosition))

#: Цвет подложки бейджа по умолчанию (читаемый акцент, не зависит от палитры концепции).
BADGE_BACKGROUND = "#c0392b"


class _RoleStyle:
    """Стиль роли текстового блока: кегль в долях высоты холста + оформление."""

    __slots__ = ("font_fraction", "weight", "align", "max_width", "position")

    def __init__(
        self,
        font_fraction: float,
        weight: str,
        align: str,
        max_width: float,
        position: str,
    ) -> None:
        self.font_fraction = font_fraction
        self.weight = weight
        self.align = align
        self.max_width = max_width
        self.position = position


# Роль → оформление. Кегль задаётся долей высоты холста, чтобы текст одинаково
# смотрелся на карточках разного размера (1000² Ozon vs 900×1200 WB).
ROLE_STYLES: dict[str, _RoleStyle] = {
    "headline": _RoleStyle(0.085, "bold", "center", 0.86, "top-center"),
    "subheadline": _RoleStyle(0.052, "normal", "center", 0.82, "bottom-center"),
    "bullet": _RoleStyle(0.040, "normal", "left", 0.62, "middle-left"),
    "caption": _RoleStyle(0.032, "normal", "center", 0.80, "bottom-center"),
    "spec": _RoleStyle(0.040, "bold", "left", 0.60, "bottom-left"),
    "badge": _RoleStyle(0.044, "bold", "center", 0.40, "top-right"),
}
_DEFAULT_STYLE = _RoleStyle(0.040, "normal", "center", 0.80, "center")


def _style_for(role: str) -> _RoleStyle:
    return ROLE_STYLES.get(role, _DEFAULT_STYLE)


def _position_for(block: TextBlock, style: _RoleStyle) -> str:
    """Позиция блока: из концепции (если попадает в сетку) либо дефолт роли."""
    candidate = (block.position or "").strip().lower()
    return candidate if candidate in _GRID_POSITIONS else style.position


def _make_block(text: str, role: str, position: str, canvas: Canvas) -> RenderBlock:
    """Собрать :class:`RenderBlock` для текста с оформлением роли."""
    style = _style_for(role)
    font_size = max(12, round(style.font_fraction * canvas.height))
    is_badge = role == "badge"
    return RenderBlock(
        text=text,
        position=position,  # type: ignore[arg-type]  # уже проверено по _GRID_POSITIONS/дефолту
        font_size=font_size,
        color="#ffffff" if is_badge else "#111111",
        weight=style.weight,  # type: ignore[arg-type]
        align=style.align,  # type: ignore[arg-type]
        max_width=style.max_width,
        background=BADGE_BACKGROUND if is_badge else None,
        padding=round(font_size * 0.4) if is_badge else 0,
    )


def concept_to_render_blocks(
    concept: CardConcept, template: MarketplaceTemplate
) -> list[RenderBlock]:
    """Перевести текстовые блоки концепции в блоки рендера по шаблону (чистая функция).

    Пункты-преимущества («bullet») сливаются в один маркированный блок. Итог
    усечён до ``template.max_text_blocks`` (читаемость карточки маркетплейса).
    """
    canvas = template.canvas
    blocks: list[RenderBlock] = []
    bullets: list[TextBlock] = []
    for text_block in concept.text_blocks:
        if not text_block.text.strip():
            continue
        if text_block.role == "bullet":
            bullets.append(text_block)
            continue
        style = _style_for(text_block.role)
        position = _position_for(text_block, style)
        blocks.append(_make_block(text_block.text, text_block.role, position, canvas))

    if bullets:
        style = _style_for("bullet")
        merged = "\n".join(f"• {b.text}" for b in bullets)
        position = _position_for(bullets[0], style)
        blocks.append(_make_block(merged, "bullet", position, canvas))

    return blocks[: template.max_text_blocks]


def build_card_render_request(
    base_image: ImageRef,
    concept: CardConcept,
    template: MarketplaceTemplate | None = None,
) -> RenderRequest:
    """Собрать запрос на наложение текста: блоки концепции + холст и safe-zone шаблона."""
    template = template or get_template()
    return RenderRequest(
        base_image=base_image,
        blocks=concept_to_render_blocks(concept, template),
        canvas=template.canvas,
        safe_zone=template.safe_zone,
    )


async def render_card_text(
    renderer: TextRenderer,
    base_image: ImageRef,
    concept: CardConcept,
    template: MarketplaceTemplate | None = None,
) -> RenderResult:
    """Наложить текст концепции на изображение карточки выбранным рендерером (стадия [6])."""
    request = build_card_render_request(base_image, concept, template)
    return await renderer.render(request)

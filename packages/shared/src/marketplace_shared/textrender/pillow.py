"""Pillow-бэкенд движка текста — офлайн-fallback (стадия [6], docs_marketplace/plan.md, раздел 6).

Рисует текстовые блоки прямо на изображении средствами Pillow: без браузера, без
сети, детерминированно. Это осознанный fallback для простых подписей и для окружений
без Chromium; основной режим со сложной типографикой/инфографикой — Playwright
(HTML/CSS), см. :mod:`marketplace_shared.textrender.playwright`.

Логика раскладки вынесена в чистые функции (перенос строк, якорь по сетке 3×3) —
их удобно тестировать без IO.
"""

from __future__ import annotations

import io

from PIL import Image, ImageColor, ImageDraw, ImageFont

from marketplace_shared.providers.contracts import ImageRef

from .base import TextRenderer
from .contracts import Canvas, GridPosition, RenderBlock, RenderRequest, RenderResult

#: Доля меньшей стороны холста под безопасное поле от краёв (черновая safe-zone;
#: точные safe-zones по маркетплейсам — отдельный пункт Этапа 3).
DEFAULT_MARGIN_FRACTION = 0.04

#: Кандидаты шрифтов с кириллицей (Linux-контейнер, Windows). Последний рубеж —
#: встроенный в Pillow дефолт (load_default(size)).
_FONT_CANDIDATES_REGULAR = (
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "arial.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
)
_FONT_CANDIDATES_BOLD = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "arialbd.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
)


def _load_font(size: int, *, bold: bool, font_path: str | None) -> ImageFont.FreeTypeFont:
    """Подобрать TTF-шрифт нужного кегля (с кириллицей), иначе — дефолт Pillow."""
    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    candidates += list(_FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REGULAR)
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default(size=size)


def _parse_color(value: str, *, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Разобрать HEX/имя цвета в RGBA; при ошибке — ``default``."""
    try:
        rgb = ImageColor.getrgb(value)
    except ValueError:
        return default
    if len(rgb) == 3:
        return (*rgb, 255)
    return rgb  # уже RGBA


def wrap_lines(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float
) -> list[str]:
    """Перенести текст по словам так, чтобы строки влезали в ``max_width`` (px).

    Чистая (зависит только от метрик шрифта). Слишком длинное одиночное слово
    оставляется как есть — лучше выйти за поле, чем потерять текст.
    """
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip()
            if not current or draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def anchor_xy(
    position: GridPosition,
    block_w: float,
    block_h: float,
    box: tuple[int, int, int, int],
) -> tuple[float, float]:
    """Левый-верхний угол блока размера ``block_w×block_h`` в зоне ``box`` по сетке 3×3."""
    left, top, right, bottom = box
    vertical, _, horizontal = position.partition("-")
    # Горизонталь
    if horizontal == "left":
        x = left
    elif horizontal == "right":
        x = right - block_w
    else:  # center
        x = left + (right - left - block_w) / 2
    # Вертикаль
    if vertical == "top":
        y = top
    elif vertical == "bottom":
        y = bottom - block_h
    else:  # middle
        y = top + (bottom - top - block_h) / 2
    return x, y


def _default_box(canvas: Canvas) -> tuple[int, int, int, int]:
    """Прямоугольник безопасной зоны по умолчанию (равный отступ от краёв)."""
    margin = int(min(canvas.width, canvas.height) * DEFAULT_MARGIN_FRACTION)
    return (margin, margin, canvas.width - margin, canvas.height - margin)


def _draw_block(
    image: Image.Image,
    block: RenderBlock,
    canvas: Canvas,
    box: tuple[int, int, int, int],
    *,
    font_path: str | None,
) -> None:
    """Нарисовать один блок поверх ``image`` в безопасной зоне ``box`` (in-place)."""
    draw = ImageDraw.Draw(image)
    font = _load_font(block.font_size, bold=block.weight == "bold", font_path=font_path)
    max_width = block.max_width * canvas.width - 2 * block.padding

    lines = wrap_lines(draw, block.text, font, max_width)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    line_widths = [draw.textlength(line, font=font) for line in lines]
    text_w = max(line_widths, default=0.0)
    text_h = line_h * len(lines)

    block_w = text_w + 2 * block.padding
    block_h = text_h + 2 * block.padding
    x0, y0 = anchor_xy(block.position, block_w, block_h, box)

    if block.background is not None:
        plate = _parse_color(block.background, default=(0, 0, 0, 0))
        draw.rectangle((x0, y0, x0 + block_w, y0 + block_h), fill=plate)

    color = _parse_color(block.color, default=(17, 17, 17, 255))
    text_x0 = x0 + block.padding
    text_y = y0 + block.padding
    for line, width in zip(lines, line_widths, strict=True):
        if block.align == "left":
            lx = text_x0
        elif block.align == "right":
            lx = text_x0 + (text_w - width)
        else:  # center
            lx = text_x0 + (text_w - width) / 2
        draw.text((lx, text_y), line, font=font, fill=color)
        text_y += line_h


def render_blocks(image: Image.Image, request: RenderRequest, *, font_path: str | None) -> bytes:
    """Наложить все блоки на изображение и вернуть PNG-байты (RGB).

    Чистая по отношению к IO: на вход — уже загруженное изображение. Удобно
    тестировать без сети/хранилища.
    """
    canvas = TextRenderer.canvas_of(request, image)
    box = request.safe_zone.box(canvas) if request.safe_zone is not None else _default_box(canvas)
    composed = image.convert("RGBA")
    for block in request.blocks:
        _draw_block(composed, block, canvas, box, font_path=font_path)
    buf = io.BytesIO()
    composed.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


class PillowTextRenderer(TextRenderer):
    """Наложение текста средствами Pillow (без браузера) — офлайн-fallback стадии [6]."""

    name = "pillow"

    def __init__(self, *, font_path: str | None = None) -> None:
        self._font_path = font_path

    async def render(self, request: RenderRequest) -> RenderResult:
        image = await self._load_base(request)
        png = render_blocks(image, request, font_path=self._font_path)
        return RenderResult(
            image=ImageRef(data=png, media_type="image/png"),
            renderer=self.name,
            raw={"blocks": len(request.blocks)},
        )

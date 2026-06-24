"""Playwright-бэкенд движка текста — основной режим (стадия [6], docs_marketplace/plan.md, разд. 6).

Дизайнер авторит раскладку привычными веб-средствами (HTML/CSS), а headless Chromium
рендерит прозрачный оверлей, который накладывается на изображение карточки. Это даёт
сложную типографику и инфографику, недоступную простому Pillow-fallback.

Playwright и браузер ставятся из extra ``render`` тяжёлого воркера и в тонкий образ
не входят, поэтому импорт ленивый: при отсутствии зависимости — понятная
:class:`RendererNotAvailable` (а не ImportError на старте процесса).

Построение HTML из блоков вынесено в чистую :func:`build_overlay_html` — её можно
тестировать без браузера; «сырой» ``request.html`` (шаблоны Этапа 3) имеет приоритет.
"""

from __future__ import annotations

import html as html_lib
import io

from PIL import Image

from .base import TextRenderer
from .contracts import Canvas, RenderBlock, RenderRequest, RenderResult, SafeZone
from .errors import RendererNotAvailable

# Перевод позиции сетки 3×3 в CSS-выравнивание контейнера (flex).
_VERTICAL = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}
_HORIZONTAL = {"left": "flex-start", "center": "center", "right": "flex-end"}


def _split_position(position: str) -> tuple[str, str]:
    """Разложить позицию сетки в (вертикаль, горизонталь). 'center' → ('middle','center')."""
    if position == "center":
        return "middle", "center"
    vertical, _, horizontal = position.partition("-")
    return vertical, horizontal


def _safe_padding_css(request: RenderRequest, canvas: Canvas) -> str:
    """CSS-падинг контейнера блоков из безопасной зоны (px по сторонам)."""
    zone = request.safe_zone or SafeZone()
    top = int(zone.top * canvas.height)
    right = int(zone.right * canvas.width)
    bottom = int(zone.bottom * canvas.height)
    left = int(zone.left * canvas.width)
    return f"{top}px {right}px {bottom}px {left}px"


def _block_css(block: RenderBlock, canvas: Canvas, pad_css: str) -> str:
    """CSS одного блока: безопасное поле, позиция по сетке, кегль, цвет, плашка."""
    vertical, horizontal = _split_position(block.position)
    max_width_px = int(block.max_width * canvas.width)
    rules = [
        "position:absolute",
        "display:flex",
        "inset:0",
        f"padding:{pad_css}",
        f"align-items:{_VERTICAL[vertical]}",
        f"justify-content:{_HORIZONTAL[horizontal]}",
        "box-sizing:border-box",
    ]
    inner = [
        f"max-width:{max_width_px}px",
        f"font-size:{block.font_size}px",
        f"font-weight:{700 if block.weight == 'bold' else 400}",
        f"color:{block.color}",
        f"text-align:{block.align}",
        "line-height:1.15",
        "white-space:pre-wrap",
        "word-wrap:break-word",
    ]
    if block.padding:
        inner.append(f"padding:{block.padding}px")
    if block.background is not None:
        inner.append(f"background:{block.background}")
    return f"<div style=\"{';'.join(rules)}\"><div style=\"{';'.join(inner)}\">{{text}}</div></div>"


def build_overlay_html(request: RenderRequest, canvas: Canvas) -> str:
    """Собрать HTML прозрачного оверлея из блоков (чистая функция).

    Текст экранируется (защита от поломки разметки). Фон страницы прозрачный —
    оверлей композитится поверх изображения карточки.
    """
    if request.html is not None:
        return request.html
    pad_css = _safe_padding_css(request, canvas)
    layers = []
    for block in request.blocks:
        layers.append(_block_css(block, canvas, pad_css).format(text=html_lib.escape(block.text)))
    body = "".join(layers)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>*{margin:0;padding:0}"
        "html,body{background:transparent;font-family:'DejaVu Sans',Arial,sans-serif}"
        f"#card{{position:relative;width:{canvas.width}px;height:{canvas.height}px}}"
        "</style></head>"
        f"<body><div id='card'>{body}</div></body></html>"
    )


class PlaywrightTextRenderer(TextRenderer):
    """Наложение текста через headless Chromium (HTML/CSS) — основной режим стадии [6]."""

    name = "playwright"

    def __init__(self, *, font_path: str | None = None) -> None:
        # font_path принимается для единообразия с Pillow-бэкендом; в браузере шрифты
        # подключаются через CSS/@font-face в шаблонах (Этап 3).
        self._font_path = font_path

    async def render(self, request: RenderRequest) -> RenderResult:
        from marketplace_shared.providers.contracts import ImageRef

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - зависит от extra `render`
            raise RendererNotAvailable(
                "Playwright не установлен; поставьте extra воркера 'render' "
                "(uv sync --extra render) и браузер (playwright install chromium), "
                "либо используйте TEXT_RENDERER='pillow'"
            ) from exc

        base = await self._load_base(request)
        canvas = self.canvas_of(request, base)
        overlay_html = build_overlay_html(request, canvas)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(
                    viewport={"width": canvas.width, "height": canvas.height},
                    device_scale_factor=1,
                )
                await page.set_content(overlay_html, wait_until="networkidle")
                overlay_png = await page.screenshot(omit_background=True, type="png")
            finally:
                await browser.close()

        overlay = Image.open(io.BytesIO(overlay_png)).convert("RGBA")
        if overlay.size != base.size:
            overlay = overlay.resize(base.size)
        composed = Image.alpha_composite(base, overlay).convert("RGB")
        buf = io.BytesIO()
        composed.save(buf, format="PNG")
        return RenderResult(
            image=ImageRef(data=buf.getvalue(), media_type="image/png"),
            renderer=self.name,
            raw={"blocks": len(request.blocks)},
        )

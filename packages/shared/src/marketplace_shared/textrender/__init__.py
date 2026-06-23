"""Движок наложения текста — стадия [6] (docs/plan.md, разделы 3 и 6).

Текст накладывается **отдельным детерминированным этапом**, а не нейросетью: это
даёт читаемость и точное попадание в требования маркетплейсов. Движок берёт
изображение со стадии [5] и кладёт поверх текстовые блоки.

Backend выбирается реестром по конфигу (`TEXT_RENDERER`), как и провайдеры:
- ``playwright`` — основной режим (HTML/CSS через headless Chromium, extra `render`);
- ``pillow`` — офлайн-fallback и дефолт (без браузера, без сети).

Маппинг визуальной концепции стадии [3] и шаблонов маркетплейсов в блоки рендера —
отдельные пункты Этапа 3 (см. docs/plan.md, раздел 7).
"""

from __future__ import annotations

from .base import TextRenderer
from .config import TextRenderSettings, get_text_render_settings
from .contracts import (
    Align,
    Canvas,
    GridPosition,
    RenderBlock,
    RenderRequest,
    RenderResult,
    Weight,
)
from .errors import RendererNotAvailable, RendererNotConfigured, TextRenderError
from .pillow import PillowTextRenderer, render_blocks, wrap_lines
from .playwright import PlaywrightTextRenderer, build_overlay_html
from .registry import available_text_renderers, get_text_renderer

__all__ = [
    # контракты
    "RenderBlock",
    "Canvas",
    "RenderRequest",
    "RenderResult",
    "GridPosition",
    "Align",
    "Weight",
    # интерфейс и backend'ы
    "TextRenderer",
    "PillowTextRenderer",
    "PlaywrightTextRenderer",
    "render_blocks",
    "wrap_lines",
    "build_overlay_html",
    # конфиг и реестр
    "TextRenderSettings",
    "get_text_render_settings",
    "get_text_renderer",
    "available_text_renderers",
    # ошибки
    "TextRenderError",
    "RendererNotConfigured",
    "RendererNotAvailable",
]

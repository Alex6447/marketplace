"""Фабрика движка наложения текста: выбор backend'а по конфигурации.

`get_text_renderer` — единственная точка, где имя из ``TEXT_RENDERER`` превращается в
конкретный backend. Стадия [6] зовёт только её и работает с интерфейсом
:class:`TextRenderer`. Регистрация — явный словарь builder'ов (как в провайдерах).
"""

from __future__ import annotations

from collections.abc import Callable

from .base import TextRenderer
from .config import TextRenderSettings, get_text_render_settings
from .errors import RendererNotConfigured
from .pillow import PillowTextRenderer
from .playwright import PlaywrightTextRenderer

RendererBuilder = Callable[[TextRenderSettings], TextRenderer]

_RENDERER_BUILDERS: dict[str, RendererBuilder] = {
    "pillow": lambda s: PillowTextRenderer(font_path=s.text_render_font),
    "playwright": lambda s: PlaywrightTextRenderer(font_path=s.text_render_font),
}


def available_text_renderers() -> list[str]:
    """Имена зарегистрированных backend'ов наложения текста."""
    return sorted(_RENDERER_BUILDERS)


def get_text_renderer(settings: TextRenderSettings | None = None) -> TextRenderer:
    """Создать backend наложения текста согласно конфигурации (`TEXT_RENDERER`)."""
    settings = settings or get_text_render_settings()
    try:
        builder = _RENDERER_BUILDERS[settings.text_renderer]
    except KeyError:
        raise RendererNotConfigured(
            f"Неизвестный TEXT_RENDERER={settings.text_renderer!r}; "
            f"доступны: {available_text_renderers()}"
        ) from None
    return builder(settings)

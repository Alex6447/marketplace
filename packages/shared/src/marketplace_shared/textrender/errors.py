"""Исключения движка наложения текста (стадия [6])."""

from __future__ import annotations


class TextRenderError(RuntimeError):
    """Базовая ошибка движка рендера текста."""


class RendererNotConfigured(TextRenderError):
    """Выбран неизвестный рендерер (`TEXT_RENDERER`)."""


class RendererNotAvailable(TextRenderError):
    """Рендерер выбран, но его зависимости не установлены.

    Например, ``playwright`` не входит в тонкий образ — он ставится из extra
    ``render`` тяжёлого воркера (см. ``apps/worker/pyproject.toml``).
    """

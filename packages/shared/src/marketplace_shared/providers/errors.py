"""Исключения провайдер-слоя.

Иерархия позволяет вызывающему коду (стадии пайплайна) отличать «провайдер не
настроен» (ошибка конфигурации/окружения) от «метод ещё не реализован» (каркас
hosted-провайдера, наполняется в следующих пунктах плана).
"""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Базовая ошибка провайдер-слоя."""


class ProviderNotConfigured(ProviderError):
    """Провайдер выбран, но не сконфигурирован.

    Неизвестное имя в `LLM_PROVIDER`/`IMAGE_PROVIDER` или отсутствует обязательный
    ключ доступа (например, `ANTHROPIC_API_KEY`).
    """


class ProviderNotImplemented(ProviderError, NotImplementedError):
    """Метод hosted-провайдера ещё не реализован.

    Каркас зафиксирован в пункте «Абстракции LLMProvider/ImageProvider», а реальные
    сетевые вызовы наполняются в пунктах «Подключение Claude API» и
    «Подключение editing-API» (см. docs_marketplace/plan.md, раздел 7, Этап 0).
    """


class TransientProviderError(ProviderError):
    """Временная ошибка провайдера — имеет смысл повторить.

    Сетевые сбои, таймауты, ответы 429/5xx внешнего API. В отличие от
    :class:`ProviderNotConfigured` (ошибка конфигурации) и обычной
    :class:`ProviderError` (логическая/постоянная), эту ошибку Celery-задача
    повторяет с экспоненциальным backoff (см. worker, docs_marketplace/plan.md, Этап 5).
    """

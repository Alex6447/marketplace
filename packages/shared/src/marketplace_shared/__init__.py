"""Общий код api/worker: Pydantic-контракты и провайдер-абстракции.

Провайдер-слой — в подпакете :mod:`marketplace_shared.providers` (интерфейсы
LLMProvider/ImageProvider, контракты, конфиг и фабрики; см. docs_marketplace/plan.md, 4.1).
Модель данных и прочие контракты добавляются на последующих этапах (раздел 5).
"""

__version__ = "0.1.0"

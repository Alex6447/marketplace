"""Перегенерация адресуемой стадии по разобранному фидбэку (Этап 4, цикл правок).

Стадия [9] (:mod:`marketplace_shared.pipeline.feedback`) превращает свободный текст
менеджера в :class:`ParsedFeedback`: целевая стадия + действие + дельта-параметры.
Здесь — **провайдеро-независимое применение этих дельт**: детерминированное
изменение визуальной концепции карточки [3] по value-несущим правкам и извлечение
override'ов параметров генерации изображения [5] (seed/model).

Ключевой принцип проекта (docs_marketplace/plan.md, разделы 1 и 8): фидбэк перегенерирует
**только нужную стадию**. Поэтому:
- правка текста [6] меняет лишь текстовые блоки концепции — изображение с товаром
  переиспользуется без перегенерации (товар остаётся 1:1);
- правка концепции [3] меняет фон/композицию/палитру — изображение пересобирается
  (контент-адресуемый кэш сам решит, дёргать ли провайдера).

Детерминированно применяются только правки с заданным ``value`` (и ``remove`` по
значению). Правки-инструкции без значения (``instruction`` без ``value``) вернутся
как «непринятые» — оркестратор их фиксирует в параметрах версии для прозрачности;
их осмысленное применение — задача LLM-перегенерации концепции (отдельный путь).
"""

from __future__ import annotations

from marketplace_shared.pipeline.concepts import CardConcept, TextBlock
from marketplace_shared.pipeline.feedback import (
    ChangeOperation,
    FeedbackChange,
)

#: Скалярные текстовые поля концепции, которые можно заменить целиком (set/modify).
_SCALAR_FIELDS = frozenset({"background", "composition", "product_placement", "title"})
#: Списочные строковые поля концепции (add/remove/set по значению).
_LIST_FIELDS = frozenset(
    {"color_palette", "infographics", "icons", "must_have", "must_not_have"}
)
#: Поля-параметры генерации изображения [5] — обрабатываются отдельно (не в концепции).
_IMAGE_PARAM_FIELDS = frozenset({"seed", "model"})


def _apply_scalar(concept: CardConcept, change: FeedbackChange) -> bool:
    """Применить правку к скалярному строковому полю. Возвращает True, если применена."""
    if change.value is None or change.operation not in (
        ChangeOperation.set,
        ChangeOperation.modify,
    ):
        return False
    setattr(concept, change.field, change.value)
    return True


def _apply_list(concept: CardConcept, change: FeedbackChange) -> bool:
    """Применить правку к списочному строковому полю. Возвращает True, если применена."""
    items: list[str] = list(getattr(concept, change.field))
    if change.operation == ChangeOperation.add and change.value is not None:
        if change.value not in items:
            items.append(change.value)
    elif change.operation == ChangeOperation.remove and change.value is not None:
        items = [x for x in items if x != change.value]
    elif change.operation == ChangeOperation.set and change.value is not None:
        items = [change.value]
    else:
        return False  # modify без явной семантики / отсутствует value
    setattr(concept, change.field, items)
    return True


def _apply_text_blocks(concept: CardConcept, change: FeedbackChange) -> bool:
    """Применить правку к текстовым блокам концепции. Возвращает True, если применена."""
    if change.value is None:
        return False
    blocks = list(concept.text_blocks)
    if change.operation == ChangeOperation.add:
        # Новый блок: роль/позиция по умолчанию — финальную раскладку даст шаблон [6].
        blocks.append(TextBlock(text=change.value, role="caption", position="bottom-center"))
    elif change.operation == ChangeOperation.remove:
        blocks = [b for b in blocks if b.text != change.value]
    else:
        return False  # modify/set текстовых блоков — неоднозначно без адресации блока
    concept.text_blocks = blocks
    return True


def apply_changes_to_concept(
    concept: CardConcept, changes: list[FeedbackChange]
) -> tuple[CardConcept, list[FeedbackChange]]:
    """Применить дельты фидбэка к концепции карточки (чистая функция).

    Возвращает ``(новая_концепция, непринятые_правки)``. Исходная концепция не
    мутируется (работаем по глубокой копии). Непринятыми считаются правки без
    ``value`` или с операцией, не имеющей детерминированной семантики для поля
    (например ``modify`` списка) — их осмысленное применение требует LLM.
    Правки полей генерации (``seed``/``model``) здесь игнорируются — их извлекает
    :func:`extract_image_overrides`.
    """
    result = concept.model_copy(deep=True)
    unapplied: list[FeedbackChange] = []
    for change in changes:
        field = change.field
        if field in _IMAGE_PARAM_FIELDS:
            continue  # параметры изображения, не аспект концепции
        if field in _SCALAR_FIELDS:
            applied = _apply_scalar(result, change)
        elif field in _LIST_FIELDS:
            applied = _apply_list(result, change)
        elif field == "text_blocks":
            applied = _apply_text_blocks(result, change)
        else:
            applied = False
        if not applied:
            unapplied.append(change)
    return result, unapplied


def extract_image_overrides(changes: list[FeedbackChange]) -> dict[str, object]:
    """Извлечь override'ы параметров стадии [5] из дельт фидбэка (seed/model).

    Возвращает словарь с ключами ``seed`` (int) и/или ``model`` (str) — только для
    тех, что заданы и корректно разобраны. ``seed`` пропускается, если ``value`` не
    приводится к целому.
    """
    overrides: dict[str, object] = {}
    for change in changes:
        if change.field == "model" and change.value:
            overrides["model"] = change.value
        elif change.field == "seed" and change.value is not None:
            try:
                overrides["seed"] = int(change.value)
            except (TypeError, ValueError):
                continue
    return overrides

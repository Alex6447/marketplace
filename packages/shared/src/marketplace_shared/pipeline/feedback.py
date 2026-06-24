"""Стадия [9] — разбор свободного фидбэка менеджера (LLM). См. docs/plan.md, разделы 3 и 6.

Вход: свободный текст менеджера к версии карточки + контекст (текущая концепция
карточки [3], стиль бренда). Выход (structured JSON): структурированное действие —
**на какую стадию** пайплайна направить правку, **какое действие** выполнить
(перегенерировать / точечно скорректировать) и **дельта-параметры** (конкретные
изменения, которые применит следующая стадия).

Этот результат сохраняется в ``feedback.parsed_action_json`` и служит входом для
перегенерации нужной стадии (следующий пункт Этапа 4): фидбэк перегенерирует только
адресуемую стадию, а не весь пайплайн. Логика провайдеро-независима: на вход
приходит готовый :class:`LLMProvider`.

Контракт описан Pydantic-моделями — они же единственный источник истины для JSON
Schema, которую мы отдаём LLM (`response_schema`), и для валидации её ответа.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from marketplace_shared.pipeline.concepts import CardConcept
from marketplace_shared.providers.base import LLMProvider
from marketplace_shared.providers.contracts import LLMMessage, LLMRequest, LLMResponse
from marketplace_shared.providers.errors import ProviderError

# --------------------------------------------------------------------------- #
# Перечисления контракта
# --------------------------------------------------------------------------- #


class FeedbackStage(StrEnum):
    """Стадия пайплайна, на которую направлена правка фидбэка.

    Порядок отражает пайплайн; значения совпадают со смыслом стадий раздела 3:
    идеи [2] → концепция [3] → изображение [5] → текст [6]. ``unknown`` — фидбэк
    не удалось уверенно отнести к стадии (нужно уточнение у менеджера).
    """

    concept = "concept"  # [3] — композиция, фон, подача товара, палитра, тексты-замысел
    image = "image"  # [5] — пересборка изображения (фон/сцена, seed), товар сохраняется
    text = "text"  # [6] — наложенный текст: формулировки, размер, позиция, цвет
    ideas = "ideas"  # [2] — пересмотр самого плана комплекта (роль/смыслы слайда)
    unknown = "unknown"  # фидбэк неоднозначен — требуется уточнение


class FeedbackActionType(StrEnum):
    """Что сделать с адресуемой стадией по фидбэку."""

    adjust = "adjust"  # точечно изменить параметры стадии и перегенерировать
    regenerate = "regenerate"  # перегенерировать стадию заново (без точечных дельт)


class ChangeOperation(StrEnum):
    """Тип дельта-изменения над полем/аспектом стадии."""

    set = "set"  # задать/заменить значение
    add = "add"  # добавить элемент (в список: иконку, текстовый блок, пункт)
    remove = "remove"  # убрать элемент/аспект
    modify = "modify"  # изменить существующий элемент (переформулировать, сдвинуть)


# --------------------------------------------------------------------------- #
# Контракт результата (он же — JSON Schema для LLM)
# --------------------------------------------------------------------------- #


class FeedbackChange(BaseModel):
    """Одна дельта-правка: к какому аспекту стадии относится и что с ним сделать.

    ``field`` называет аспект на языке концепции карточки, где это применимо
    (``background``, ``product_placement``, ``composition``, ``color_palette``,
    ``text_blocks``, ``infographics``, ``icons``, ``must_have``, ``must_not_have``),
    либо параметр генерации (``seed``, ``model``) для стадии изображения. ``value`` —
    желаемое значение (опционально; для ``remove`` обычно не нужно). ``instruction``
    — человекочитаемое указание, которое применит следующая стадия.
    """

    field: str = Field(
        description=(
            "Аспект/поле стадии, к которому относится правка "
            "(например background, color_palette, text_blocks, seed)."
        )
    )
    operation: ChangeOperation = Field(description="Тип изменения: set/add/remove/modify.")
    instruction: str = Field(
        description="Что именно изменить, человекочитаемо (переформулировка фидбэка в правку)."
    )
    value: str | None = Field(
        default=None,
        description="Желаемое значение, если применимо (например новый цвет фона, новый текст).",
    )


class ParsedFeedback(BaseModel):
    """Структурированный разбор фидбэка — результат стадии [9]."""

    summary: str = Field(description="Краткая суть фидбэка одним предложением.")
    target_stage: FeedbackStage = Field(
        description="Стадия пайплайна, которую нужно перегенерировать по фидбэку."
    )
    action: FeedbackActionType = Field(
        description="Действие: adjust (точечная правка) или regenerate (заново)."
    )
    changes: list[FeedbackChange] = Field(
        default_factory=list,
        description="Дельта-параметры — конкретные изменения для адресуемой стадии.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Уверенность в разборе (0–1). Низкая → стоит уточнить у менеджера.",
    )
    notes: str | None = Field(
        default=None,
        description="Замечания/уточнения для менеджера, если фидбэк неоднозначен.",
    )


# Схема результата для structured-вывода LLM. Pydantic строит её с внутренними
# ссылками ($defs/$ref) и enum — провайдеры (Claude) и echo-стаб их понимают.
FEEDBACK_RESPONSE_SCHEMA = ParsedFeedback.model_json_schema()


# --------------------------------------------------------------------------- #
# Вход стадии
# --------------------------------------------------------------------------- #


class FeedbackInput(BaseModel):
    """Контекст для разбора фидбэка: текст менеджера + текущее состояние карточки."""

    feedback_text: str = Field(description="Свободный текст фидбэка менеджера.")
    #: Текущая концепция карточки [3] — чтобы LLM знал, какие аспекты можно править.
    concept: CardConcept | None = None
    #: Стиль бренда (из проекта) — тон и визуальные правила.
    brand_style: str | None = None


# --------------------------------------------------------------------------- #
# Построение запроса и вызов
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = (
    "Ты — продюсер пайплайна генерации карточек товара для маркетплейсов. Менеджер "
    "оставляет свободный текстовый фидбэк к версии карточки, а ты переводишь его в "
    "структурированное действие для пайплайна. Пайплайн состоит из стадий: "
    "[ideas] план комплекта (роли и смыслы слайдов); "
    "[concept] визуальная концепция карточки (композиция, подача товара, фон/сцена, "
    "цветовая палитра, инфографика, иконки, замысел текстовых блоков, must_have/"
    "must_not_have); "
    "[image] генерация изображения (фон/сцена; товар берётся с реального фото и "
    "сохраняется без искажений — его форму/цвет/детали менять НЕЛЬЗЯ); "
    "[text] детерминированное наложение текста (формулировки, размер, позиция, цвет). "
    "Определи МИНИМАЛЬНУЮ стадию, которую нужно тронуть: правка только текста — стадия "
    "[text]; смена фона/сцены/композиции/палитры — [concept]; претензия к самой картинке "
    "при неизменной концепции (артефакты, перегенерировать) — [image]; пересмотр набора "
    "слайдов — [ideas]. Если фидбэк просит исказить, перерисовать или заменить сам товар "
    "— это нарушает инвариант проекта: вынеси такой запрет в notes и не предлагай менять "
    "товар. Действие adjust — когда есть конкретные точечные правки (заполни changes); "
    "regenerate — когда просят просто сделать заново. В changes описывай дельты на языке "
    "полей концепции (background, composition, product_placement, color_palette, "
    "text_blocks, infographics, icons, must_have, must_not_have) или параметров "
    "генерации (seed, model). Если фидбэк неоднозначен — target_stage=unknown, низкая "
    "confidence, уточнение в notes. Пиши на русском. Верни строго структуру по JSON-схеме."
)


def _format_concept(concept: CardConcept) -> str:
    """Сериализовать текущую концепцию карточки в читаемый для LLM текст."""
    lines = [
        f"Роль слайда: {concept.role}",
        f"Заголовок концепции: {concept.title}",
        f"Композиция: {concept.composition}",
        f"Подача товара: {concept.product_placement}",
        f"Фон/сцена: {concept.background}",
    ]
    if concept.color_palette:
        lines.append(f"Палитра: {', '.join(concept.color_palette)}")
    if concept.text_blocks:
        blocks = "; ".join(
            f"[{block.role}/{block.position}] {block.text}" for block in concept.text_blocks
        )
        lines.append(f"Текстовые блоки: {blocks}")
    if concept.infographics:
        lines.append(f"Инфографика: {', '.join(concept.infographics)}")
    if concept.icons:
        lines.append(f"Иконки: {', '.join(concept.icons)}")
    if concept.must_have:
        lines.append(f"Обязательно: {', '.join(concept.must_have)}")
    if concept.must_not_have:
        lines.append(f"Запрещено: {', '.join(concept.must_not_have)}")
    return "\n".join(lines)


def _format_input(feedback: FeedbackInput) -> str:
    """Собрать пользовательское сообщение: контекст карточки + фидбэк."""
    lines: list[str] = []
    if feedback.brand_style:
        lines.append(f"Стиль бренда: {feedback.brand_style}")
    if feedback.concept is not None:
        lines.append("Текущая концепция карточки:")
        lines.append(_format_concept(feedback.concept))
        lines.append("")
    lines.append(f"Фидбэк менеджера: {feedback.feedback_text}")
    return "\n".join(lines)


def build_feedback_request(
    feedback: FeedbackInput,
    *,
    model: str | None = None,
    max_tokens: int = 1536,
) -> LLMRequest:
    """Собрать запрос к LLM для стадии [9]. Чистая функция — удобно тестировать."""
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=_format_input(feedback)),
        ],
        model=model,
        max_tokens=max_tokens,
        response_schema=FEEDBACK_RESPONSE_SCHEMA,
    )


async def parse_feedback(
    provider: LLMProvider,
    feedback: FeedbackInput,
    *,
    model: str | None = None,
    max_tokens: int = 1536,
) -> tuple[ParsedFeedback, LLMResponse]:
    """Разобрать свободный фидбэк менеджера в структурированное действие.

    Возвращает валидированный :class:`ParsedFeedback` (действие + стадия + дельты) и
    «сырой» :class:`LLMResponse` (для учёта стоимости/трейсинга — usage, модель).
    """
    request = build_feedback_request(feedback, model=model, max_tokens=max_tokens)
    response = await provider.complete(request)
    if response.data is None:
        raise ProviderError(
            "LLM не вернул структурированный ответ для разбора фидбэка "
            f"(провайдер {response.provider!r}, модель {response.model!r})"
        )
    parsed = ParsedFeedback.model_validate(response.data)
    return parsed, response

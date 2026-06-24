"""Стадия [3] — визуальная концепция карточек (LLM). См. docs_marketplace/plan.md, разделы 3 и 6.

Вход: бриф товара (тот же, что у стадии [2]) + идеи комплекта (результат стадии [2]).
Выход (structured JSON): для каждой карточки — визуальная концепция: композиция,
позиция товара, фон, инфографика, текстовые блоки (текст + позиция + роль), иконки,
цветовая палитра и списки «что должно быть / чего быть не должно».

Этот JSON — **единый контракт** между LLM и детерминированным движком наложения
текста (стадия [6]): из него движок берёт текстовые блоки и их раскладку. Контракт
описан Pydantic-моделями — они же единственный источник истины для JSON Schema,
которую мы отдаём LLM (`response_schema`), и для валидации её ответа. Логика
провайдеро-независима: на вход приходит готовый :class:`LLMProvider`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from marketplace_shared.pipeline.ideas import ProductBrief, ProductIdeas
from marketplace_shared.providers.base import LLMProvider
from marketplace_shared.providers.contracts import LLMMessage, LLMRequest, LLMResponse
from marketplace_shared.providers.errors import ProviderError

# Рекомендованные позиции элементов на карточке (сетка 3×3 + центр).
# Подсказка для LLM и движка текста, а не жёсткое ограничение схемы.
RECOMMENDED_POSITIONS = (
    "top-left",
    "top-center",
    "top-right",
    "middle-left",
    "center",
    "middle-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)

# Роли текстовых блоков — для движка наложения текста (стадия [6]).
RECOMMENDED_TEXT_ROLES = (
    "headline",  # крупный заголовок
    "subheadline",  # подзаголовок
    "bullet",  # пункт списка преимуществ
    "caption",  # подпись / пояснение
    "badge",  # плашка/бейдж (скидка, новинка, гарантия)
    "spec",  # характеристика (значение + подпись)
)


# --------------------------------------------------------------------------- #
# Контракт результата (он же — JSON Schema для LLM)
# --------------------------------------------------------------------------- #


class TextBlock(BaseModel):
    """Текстовый блок карточки — вход для детерминированного движка текста [6]."""

    text: str = Field(description="Текст блока (на языке карточки).")
    role: str = Field(
        description="Роль блока: headline/subheadline/bullet/caption/badge/spec и т.п."
    )
    position: str = Field(
        description="Позиция блока на карточке (например top-left, center, bottom-right)."
    )
    emphasis: str | None = Field(
        default=None,
        description="Акцент оформления (например: крупно, цвет бренда, контурный текст).",
    )


class CardConcept(BaseModel):
    """Визуальная концепция одной карточки — единый контракт LLM ↔ движок текста."""

    role: str = Field(description="Роль слайда (совпадает с ролью идеи из стадии [2]).")
    title: str = Field(description="Короткий рабочий заголовок концепции карточки.")
    composition: str = Field(
        description="Описание композиции/раскладки (где товар, где текст, баланс)."
    )
    product_placement: str = Field(
        description="Позиция и подача товара в кадре (ракурс, масштаб, зона)."
    )
    background: str = Field(description="Фон/сцена карточки (для стадии генерации [5]).")
    text_blocks: list[TextBlock] = Field(
        default_factory=list,
        description="Текстовые блоки карточки с текстом, ролью и позицией.",
    )
    infographics: list[str] = Field(
        default_factory=list,
        description="Инфографические элементы (схемы, диаграммы, выноски).",
    )
    icons: list[str] = Field(
        default_factory=list, description="Иконки/пиктограммы, которые стоит использовать."
    )
    color_palette: list[str] = Field(
        default_factory=list,
        description="Цветовая палитра карточки (названия или HEX).",
    )
    must_have: list[str] = Field(
        default_factory=list,
        description="Что обязательно должно быть на карточке.",
    )
    must_not_have: list[str] = Field(
        default_factory=list,
        description="Чего на карточке быть не должно (запреты для генерации).",
    )


class CardSetConcepts(BaseModel):
    """Комплект визуальных концепций — результат стадии [3]."""

    cards: list[CardConcept] = Field(
        description="Концепции карточек в порядке показа (как правило, по одной на идею)."
    )


# Схема результата для structured-вывода LLM. Pydantic строит её с внутренними
# ссылками ($defs/$ref) — провайдеры (Claude) и echo-стаб их понимают.
CONCEPTS_RESPONSE_SCHEMA = CardSetConcepts.model_json_schema()


# --------------------------------------------------------------------------- #
# Построение запроса и вызов
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = (
    "Ты — арт-директор, который превращает план комплекта карточек товара в точные "
    "визуальные концепции для российских маркетплейсов (Ozon, Wildberries, Яндекс "
    "Маркет). Для каждого слайда из плана собери концепцию: композицию, позицию и "
    "подачу товара, фон/сцену, текстовые блоки (текст + роль + позиция), инфографику, "
    "иконки, цветовую палитру и списки «что должно быть» и «чего быть не должно». "
    "Делай по одной концепции на слайд плана и сохраняй роль и порядок слайдов. "
    "ВАЖНО: товар берётся с реального фото и должен сохраняться без искажений — в "
    "концепции описывай фон/сцену и оформление, а не «перерисовку» товара; запреты на "
    "искажение товара добавляй в must_not_have. Тексты пиши на русском языке, кратко и "
    "по делу — их будет накладывать отдельный детерминированный движок. "
    f"Рекомендованные позиции: {', '.join(RECOMMENDED_POSITIONS)}. "
    f"Рекомендованные роли текстовых блоков: {', '.join(RECOMMENDED_TEXT_ROLES)}. "
    "Верни строго структуру по заданной JSON-схеме."
)


def _format_brief(brief: ProductBrief) -> str:
    """Сериализовать бриф товара в читаемый для LLM текст."""
    lines = [f"Товар: {brief.title}"]
    if brief.brand_style:
        lines.append(f"Стиль бренда: {brief.brand_style}")
    if brief.target_audience:
        lines.append(f"Целевая аудитория: {brief.target_audience}")
    if brief.advantages:
        lines.append(f"Преимущества: {brief.advantages}")
    if brief.attributes:
        attrs = "; ".join(f"{k}: {v}" for k, v in brief.attributes.items())
        lines.append(f"Характеристики: {attrs}")
    if brief.requirements:
        reqs = "; ".join(f"{k}: {v}" for k, v in brief.requirements.items())
        lines.append(f"Требования к карточкам: {reqs}")
    return "\n".join(lines)


def _format_ideas(ideas: ProductIdeas) -> str:
    """Сериализовать план комплекта (результат стадии [2]) в текст для LLM."""
    lines = [f"Общий тон комплекта: {ideas.overall_tone}"]
    if ideas.notes:
        lines.append(f"Замечания по комплекту: {ideas.notes}")
    lines.append("План слайдов:")
    for index, slide in enumerate(ideas.slides, start=1):
        messages = "; ".join(slide.key_messages)
        line = f"{index}. [{slide.role}] {slide.title} — смыслы: {messages}"
        if slide.accents:
            line += f"; акценты: {', '.join(slide.accents)}"
        line += f"; тон: {slide.tone}"
        lines.append(line)
    return "\n".join(lines)


def build_concepts_request(
    brief: ProductBrief,
    ideas: ProductIdeas,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
) -> LLMRequest:
    """Собрать запрос к LLM для стадии [3]. Чистая функция — удобно тестировать."""
    user_content = f"{_format_brief(brief)}\n\n{_format_ideas(ideas)}"
    return LLMRequest(
        messages=[
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_content),
        ],
        model=model,
        max_tokens=max_tokens,
        response_schema=CONCEPTS_RESPONSE_SCHEMA,
    )


async def generate_concepts(
    provider: LLMProvider,
    brief: ProductBrief,
    ideas: ProductIdeas,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
) -> tuple[CardSetConcepts, LLMResponse]:
    """Сгенерировать визуальные концепции комплекта карточек.

    Возвращает валидированный :class:`CardSetConcepts` и «сырой» :class:`LLMResponse`
    (для учёта стоимости/трейсинга — usage, модель, провайдер).
    """
    request = build_concepts_request(brief, ideas, model=model, max_tokens=max_tokens)
    response = await provider.complete(request)
    if response.data is None:
        raise ProviderError(
            "LLM не вернул структурированный ответ для стадии концепций "
            f"(провайдер {response.provider!r}, модель {response.model!r})"
        )
    concepts = CardSetConcepts.model_validate(response.data)
    return concepts, response

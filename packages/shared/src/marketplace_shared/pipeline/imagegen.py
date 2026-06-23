"""Стадия [5] — генерация изображения с сохранением товара (основной режим).

См. docs/plan.md, раздел 3 (стадия [5]) и раздел 4 (выбор инструментов). Основной
режим — **editing-модель по инструкции** (Flux.1 Kontext / Gemini 2.5 Flash Image /
Qwen-Image-Edit): «оставь товар, измени фон/сцену» с реальным фото на входе. Это
прямая митигация главного риска проекта — искажения товара (docs/plan.md, раздел 8).

Логика провайдеро-независима: на вход приходит готовый :class:`ImageProvider`
(hosted Gemini/Flux или локальный ComfyUI — выбирается реестром), фото товара и
визуальная концепция карточки (результат стадии [3]). Из концепции собирается
текстовая инструкция редактирования; сам товар берётся с фото и сохраняется 1:1 —
поэтому инструкция явно запрещает перерисовывать/искажать товар.

Текст на карточку здесь НЕ наносится: его кладёт отдельный детерминированный движок
(стадия [6]). Поэтому инструкция просит модель не добавлять надписи поверх сцены.

Помимо основного режима (editing) поддержан **композитинг (gold standard)**: фон/сцена
генерируется отдельно (:func:`generate_card_background`), а вырез товара из стадии [4]
накладывается поверх 1:1 (:func:`composite_product_on_background`) — пиксели товара
остаются ровно как на оригинале. Это самый надёжный по сохранению товара путь.
"""

from __future__ import annotations

import io

from PIL import Image

from marketplace_shared.pipeline.concepts import CardConcept
from marketplace_shared.providers.base import ImageProvider
from marketplace_shared.providers.contracts import (
    ImageEditRequest,
    ImageGenRequest,
    ImageRef,
    ImageResult,
)

# Инвариант проекта: товар сохраняется без искажений. Этот текст открывает каждую
# инструкцию редактирования — модель должна менять только фон/сцену вокруг товара.
_PRESERVE_PRODUCT = (
    "Сохрани товар с исходного фото без изменений: форма, цвет, материал, "
    "детали, логотип и пропорции должны остаться точно как на оригинале. Не "
    "перерисовывай, не дорисовывай и не заменяй товар — меняй только фон и сцену "
    "вокруг него."
)

# Текст наносится отдельной детерминированной стадией [6], не нейросетью.
_NO_TEXT = (
    "Не добавляй на изображение никаких надписей, текста, логотипов и инфографики "
    "поверх сцены — текст будет наложен отдельным этапом."
)


def build_edit_instruction(concept: CardConcept, *, brand_style: str | None = None) -> str:
    """Собрать инструкцию редактирования из визуальной концепции карточки.

    Чистая функция — удобно тестировать. Берёт из :class:`CardConcept` описание
    фона/сцены, подачи товара, композиции, палитры и запреты (``must_not_have``),
    обрамляя их инвариантом «товар без искажений» и запретом на текст.
    """
    lines = [_PRESERVE_PRODUCT]
    if concept.background:
        lines.append(f"Новый фон и сцена: {concept.background}.")
    if concept.product_placement:
        lines.append(f"Размещение и подача товара в кадре: {concept.product_placement}.")
    if concept.composition:
        lines.append(f"Композиция кадра: {concept.composition}.")
    if concept.color_palette:
        lines.append(f"Цветовая палитра сцены: {', '.join(concept.color_palette)}.")
    if brand_style:
        lines.append(f"Стиль бренда: {brand_style}.")
    if concept.must_not_have:
        lines.append("На изображении не должно быть: " + "; ".join(concept.must_not_have) + ".")
    lines.append(_NO_TEXT)
    return " ".join(lines)


async def generate_card_image(
    provider: ImageProvider,
    *,
    product_photo: ImageRef,
    concept: CardConcept,
    references: list[ImageRef] | None = None,
    brand_style: str | None = None,
    model: str | None = None,
    size: str | None = None,
    seed: int | None = None,
) -> tuple[ImageResult, str]:
    """Сгенерировать изображение карточки в основном режиме стадии [5].

    Возвращает результат image-провайдера (:class:`ImageResult`) и собранную
    инструкцию (для записи в ``CardVersion.gen_params_json`` и трейсинга).
    """
    instruction = build_edit_instruction(concept, brand_style=brand_style)
    request = ImageEditRequest(
        instruction=instruction,
        image=product_photo,
        references=references or [],
        model=model,
        size=size,
        seed=seed,
    )
    result = await provider.edit(request)
    return result, instruction


# --------------------------------------------------------------------------- #
# Композитинг (gold standard): фон генерируется, товар вставляется 1:1
# --------------------------------------------------------------------------- #

# Промт генерации фона описывает ТОЛЬКО сцену — товар вставляется отдельно (1:1),
# поэтому модель не должна рисовать ни товар, ни текст.
_BACKGROUND_ONLY = (
    "Сгенерируй только фон/сцену для карточки товара, без самого товара и без людей "
    "в центре кадра — оставь центральную зону свободной под товар, который будет "
    "вставлен отдельно. Не добавляй никакого текста, надписей и логотипов."
)


def build_background_prompt(concept: CardConcept, *, brand_style: str | None = None) -> str:
    """Собрать промт генерации фона/сцены из концепции карточки (чистая функция).

    В отличие от :func:`build_edit_instruction`, описывает только окружение: сам товар
    в композитинге не генерируется, а берётся вырезом из стадии [4] и вставляется 1:1.
    """
    lines = []
    if concept.background:
        lines.append(f"Фон и сцена: {concept.background}.")
    if concept.composition:
        lines.append(f"Композиция сцены: {concept.composition}.")
    if concept.color_palette:
        lines.append(f"Цветовая палитра: {', '.join(concept.color_palette)}.")
    if brand_style:
        lines.append(f"Стиль бренда: {brand_style}.")
    lines.append(_BACKGROUND_ONLY)
    return " ".join(lines)


def composite_product_on_background(background_png: bytes, cutout_png: bytes) -> bytes:
    """Наложить вырез товара поверх сгенерированного фона (товар = 1:1 пиксели).

    Чистая, детерминированная: фон масштабируется под размер выреза, затем вырез
    (RGBA с прозрачным фоном из стадии [4]) накладывается по альфа-каналу — пиксели
    товара остаются неизменными. Результат — непрозрачный PNG (RGB) под маркетплейсы.
    """
    foreground = Image.open(io.BytesIO(cutout_png)).convert("RGBA")
    background = Image.open(io.BytesIO(background_png)).convert("RGBA")
    if background.size != foreground.size:
        background = background.resize(foreground.size)
    composed = Image.alpha_composite(background, foreground).convert("RGB")
    buf = io.BytesIO()
    composed.save(buf, format="PNG")
    return buf.getvalue()


async def generate_card_background(
    provider: ImageProvider,
    concept: CardConcept,
    *,
    references: list[ImageRef] | None = None,
    brand_style: str | None = None,
    model: str | None = None,
    size: str | None = None,
    seed: int | None = None,
) -> tuple[ImageResult, str]:
    """Сгенерировать фон/сцену карточки (шаг композитинга стадии [5]).

    Возвращает результат image-провайдера и собранный промт (для трейсинга и записи
    в ``CardVersion.gen_params_json``). Сам композитинг выполняет
    :func:`composite_product_on_background`.
    """
    prompt = build_background_prompt(concept, brand_style=brand_style)
    request = ImageGenRequest(
        prompt=prompt,
        references=references or [],
        model=model,
        size=size,
        seed=seed,
    )
    result = await provider.generate(request)
    return result, prompt

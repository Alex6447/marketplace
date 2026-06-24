"""Стадия [7] — автоматические QA-проверки карточки (docs_marketplace/plan.md, разделы 3 и 8).

После генерации изображения [5] и наложения текста [6] карточку нужно проверить
объективно, до показа менеджеру [8]. Раздел 3 перечисляет проверки:

- **товар на месте и не искажён** — по маске товара [4] (сравнение с исходным фото);
- **текст читаем** — достаточный кегль и контраст;
- **размеры/соотношение** — под требования маркетплейса (шаблон [6]);
- **нет «запрещённых» элементов** из концепции (``must_not_have``).

Модуль провайдеро-независим и без тяжёлых зависимостей (только Pillow): на вход —
готовые байты изображений, концепция [3] и шаблон МП. Это API-first MVP: где геометрия
товара сохранена (режим ``edit``), сохранность считается попиксельно (как в
:mod:`marketplace_shared.pipeline.compare`); где товар перекомпонован (``composite``) —
он 1:1 из выреза по построению, попиксельная сверка неинформативна и помечается как
неприменимая. Сравнение эмбеддингов/SSIM по региону товара и vision-проверка
запрещённых элементов — улучшение для Этапа 6 (локальные модели).

Здесь только чистая логика: отдельные проверки (``check_*``) и сборка отчёта
(:func:`build_qa_report`). Загрузку байтов из хранилища и запись отчёта в БД делает
синхронный API-роутер (``apps/api/.../routers/qa.py``).
"""

from __future__ import annotations

import io
from typing import Literal

from PIL import Image, ImageStat
from pydantic import BaseModel, Field

from marketplace_shared.textrender import MarketplaceTemplate, RenderBlock

from .compare import compute_metrics
from .concepts import CardConcept
from .textoverlay import concept_to_render_blocks

#: Статус проверки/отчёта. ``pass``/``warn``/``fail`` влияют на агрегат; ``info`` и
#: ``skipped`` — справочные (проверка неприменима/не автоматизирована), агрегат не меняют.
QaStatus = Literal["pass", "warn", "fail", "info", "skipped"]

#: Статусы, влияющие на агрегатную оценку отчёта (по убыванию серьёзности).
_RANK: dict[str, int] = {"fail": 3, "warn": 2, "pass": 1}

# --- Пороги (вынесены, чтобы правились в одном месте) ----------------------- #
#: Сохранность товара (product_fidelity, режим edit): ≥ — ок, ниже WARN — провал.
FIDELITY_PASS = 0.85
FIDELITY_WARN = 0.60
#: Минимальный кегль текста: доля высоты холста и абсолютный пол в пикселях.
MIN_FONT_FRACTION = 0.018
MIN_FONT_PX = 14
WARN_FONT_FRACTION = 0.024
#: Контраст текста к фону (WCAG): ≥3.0 — норма для крупного текста, ниже WARN — провал.
CONTRAST_PASS = 3.0
CONTRAST_WARN = 2.0
#: Допуск соотношения сторон к требуемому шаблоном (доля).
ASPECT_TOLERANCE = 0.05
#: Белизна фона по рамке для главной карточки (средняя яркость 0..255).
WHITE_PASS = 235
WHITE_WARN = 215
#: Толщина рамки для оценки фона — доля меньшей стороны.
_BORDER_FRACTION = 0.06


class QaCheck(BaseModel):
    """Одна QA-проверка карточки: статус, человекочитаемая деталь и опц. оценка."""

    name: str = Field(description="Машинный идентификатор проверки, напр. 'dimensions'.")
    title: str = Field(description="Название проверки для UI.")
    status: QaStatus
    detail: str = Field(description="Пояснение результата на русском.")
    #: Числовая оценка проверки (если применима), нормирована по смыслу проверки.
    score: float | None = None


class QaReport(BaseModel):
    """Отчёт авто-QA версии карточки (стадия [7]) — пишется в ``qa_report_json``."""

    status: QaStatus = Field(description="Агрегат: fail при любом fail, иначе warn/pass.")
    summary: str
    checks: list[QaCheck]
    width: int
    height: int
    template_key: str


# --------------------------------------------------------------------------- #
# Вспомогательные чистые функции (цвет/геометрия)
# --------------------------------------------------------------------------- #


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """HEX/'#rgb'/'#rrggbb' → (r, g, b). Неразобранное трактуем как чёрный."""
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) >= 6:
        try:
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        except ValueError:
            return (0, 0, 0)
    return (0, 0, 0)


def _rel_luminance(rgb: tuple[int, int, int]) -> float:
    """Относительная яркость по WCAG 2.x (0..1)."""

    def chan(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def _contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Контрастное отношение по WCAG (1..21)."""
    l1, l2 = _rel_luminance(c1), _rel_luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _aspect_target(aspect_ratio: str) -> float | None:
    """'1:1' → 1.0, '3:4' → 0.75 (ширина/высота). None при неразборчивом значении."""
    try:
        w, h = aspect_ratio.split(":")
        wf, hf = float(w), float(h)
        return wf / hf if hf else None
    except (ValueError, ZeroDivisionError):
        return None


def _border_mean(image: Image.Image) -> float:
    """Средняя яркость (0..255) по рамке изображения — оценка фона главной карточки."""
    gray = image.convert("L")
    w, h = gray.size
    t = max(1, int(min(w, h) * _BORDER_FRACTION))
    # Маска: белая по рамке толщиной t, чёрная внутри — усредняем только рамку.
    mask = Image.new("L", (w, h), 255)
    mask.paste(0, (t, t, w - t, h - t))
    stat = ImageStat.Stat(gray, mask)
    return stat.mean[0] if stat.mean else 0.0


# --------------------------------------------------------------------------- #
# Отдельные проверки
# --------------------------------------------------------------------------- #


def check_dimensions(width: int, height: int, template: MarketplaceTemplate) -> QaCheck:
    """Соответствие размеров и соотношения сторон требованиям шаблона МП."""
    target = _aspect_target(template.aspect_ratio)
    actual = width / height if height else 0.0
    min_w, min_h = template.min_canvas.width, template.min_canvas.height
    size_ok = width >= min_w and height >= min_h

    if target is not None and target > 0:
        deviation = abs(actual - target) / target
        ratio_ok = deviation <= ASPECT_TOLERANCE
    else:
        ratio_ok = True

    if not ratio_ok:
        status: QaStatus = "fail"
        detail = (
            f"Соотношение {width}×{height} не соответствует {template.aspect_ratio} "
            f"шаблона «{template.title}»."
        )
    elif not size_ok:
        status = "warn"
        detail = (
            f"Размер {width}×{height} меньше минимального {min_w}×{min_h} для "
            f"«{template.title}» — возможна потеря качества при апскейле МП."
        )
    else:
        status = "pass"
        detail = f"{width}×{height} ({template.aspect_ratio}) соответствует «{template.title}»."
    return QaCheck(name="dimensions", title="Размеры и соотношение", status=status, detail=detail)


def check_text_size(blocks: list[RenderBlock], canvas_height: int) -> QaCheck:
    """Минимальный кегль текстовых блоков — достаточен ли для читаемости."""
    if not blocks:
        return QaCheck(
            name="text_size",
            title="Кегль текста",
            status="info",
            detail="Текст не накладывался — проверять нечего.",
        )
    min_font = min(b.font_size for b in blocks)
    fraction = min_font / canvas_height if canvas_height else 0.0
    if min_font < MIN_FONT_PX or fraction < MIN_FONT_FRACTION:
        status: QaStatus = "fail"
        detail = f"Минимальный кегль {min_font}px ({fraction:.1%} высоты) — слишком мелко."
    elif fraction < WARN_FONT_FRACTION:
        status = "warn"
        detail = f"Минимальный кегль {min_font}px ({fraction:.1%} высоты) — на грани читаемости."
    else:
        status = "pass"
        detail = f"Минимальный кегль {min_font}px ({fraction:.1%} высоты) — достаточно."
    return QaCheck(
        name="text_size",
        title="Кегль текста",
        status=status,
        detail=detail,
        score=round(fraction, 4),
    )


def check_text_contrast(blocks: list[RenderBlock], image_png: bytes | None) -> QaCheck:
    """Контраст текста к фону (WCAG). Грубая оценка по среднему цвету изображения.

    Для бейджа контраст считается к цвету его плашки (``background``), для остального —
    к среднему цвету изображения. Это эвристика MVP: точную область под блоком знает
    рендерер; здесь достаточно сигнала о вопиющем нечитаемом контрасте.
    """
    if not blocks:
        return QaCheck(
            name="text_contrast",
            title="Контраст текста",
            status="info",
            detail="Текст не накладывался — проверять нечего.",
        )
    if image_png is None:
        return QaCheck(
            name="text_contrast",
            title="Контраст текста",
            status="skipped",
            detail="Нет изображения для оценки контраста.",
        )
    image = Image.open(io.BytesIO(image_png)).convert("RGB")
    avg = ImageStat.Stat(image).mean
    avg_rgb = (int(avg[0]), int(avg[1]), int(avg[2]))

    min_contrast = 21.0
    for block in blocks:
        text_rgb = _hex_to_rgb(block.color)
        bg_rgb = _hex_to_rgb(block.background) if block.background else avg_rgb
        min_contrast = min(min_contrast, _contrast_ratio(text_rgb, bg_rgb))

    if min_contrast < CONTRAST_WARN:
        status: QaStatus = "fail"
        detail = f"Минимальный контраст {min_contrast:.1f}:1 — текст плохо читается."
    elif min_contrast < CONTRAST_PASS:
        status = "warn"
        detail = f"Минимальный контраст {min_contrast:.1f}:1 — ниже рекомендованного 3:1."
    else:
        status = "pass"
        detail = f"Минимальный контраст {min_contrast:.1f}:1 — достаточно."
    return QaCheck(
        name="text_contrast",
        title="Контраст текста",
        status=status,
        detail=detail,
        score=round(min_contrast, 2),
    )


def check_product_fidelity(
    *,
    source_png: bytes | None,
    image_png: bytes | None,
    mask_png: bytes | None,
    mode: str | None,
) -> QaCheck:
    """Сохранность товара: попиксельно (режим edit) либо по построению (composite)."""
    if mode == "composite":
        return QaCheck(
            name="product_fidelity",
            title="Сохранность товара",
            status="info",
            detail="Режим composite: товар вставлен 1:1 из выреза [4] — сохранён по построению.",
        )
    if not source_png or not mask_png or not image_png:
        return QaCheck(
            name="product_fidelity",
            title="Сохранность товара",
            status="skipped",
            detail="Нет маски товара [4] или исходного фото — попиксельная сверка недоступна.",
        )
    metrics = compute_metrics(source_png=source_png, result_png=image_png, mask_png=mask_png)
    fidelity = metrics.product_fidelity
    if fidelity < FIDELITY_WARN:
        status: QaStatus = "fail"
        detail = f"Сохранность товара {fidelity:.1%} — форма/цвет/детали заметно искажены."
    elif fidelity < FIDELITY_PASS:
        status = "warn"
        detail = f"Сохранность товара {fidelity:.1%} — есть дрейф пикселей товара."
    else:
        status = "pass"
        detail = f"Сохранность товара {fidelity:.1%} — товар сохранён."
    return QaCheck(
        name="product_fidelity",
        title="Сохранность товара",
        status=status,
        detail=detail,
        score=fidelity,
    )


def check_white_background(
    image_png: bytes, mask_png: bytes | None, template: MarketplaceTemplate
) -> QaCheck | None:
    """Белизна фона главной карточки (если шаблон её требует). None — проверка неприменима."""
    if not template.white_background_required:
        return None
    image = Image.open(io.BytesIO(image_png)).convert("RGB")
    mean = _border_mean(image)
    if mean >= WHITE_PASS:
        status: QaStatus = "pass"
        detail = (
            f"Фон по рамке светлый (яркость {mean:.0f}/255) — требование белого фона выполнено."
        )
    elif mean >= WHITE_WARN:
        status = "warn"
        detail = f"Фон по рамке яркость {mean:.0f}/255 — близко к границе требования белого фона."
    else:
        status = "fail"
        detail = (
            f"Фон по рамке тёмный (яркость {mean:.0f}/255) — "
            f"«{template.title}» требует белого фона."
        )
    return QaCheck(
        name="white_background",
        title="Белый фон главной карточки",
        status=status,
        detail=detail,
        score=round(mean / 255.0, 4),
    )


def check_forbidden_elements(concept: CardConcept | None) -> QaCheck:
    """Запрещённые элементы из концепции (``must_not_have``).

    Надёжная авто-проверка требует vision-модели (Этап 6); в MVP перечисляем
    ограничения как требующие визуального контроля менеджером [8] — это ``info``.
    """
    items = list(concept.must_not_have) if concept and concept.must_not_have else []
    if not items:
        return QaCheck(
            name="forbidden_elements",
            title="Запрещённые элементы",
            status="pass",
            detail="Концепция не задаёт запрещённых элементов.",
        )
    return QaCheck(
        name="forbidden_elements",
        title="Запрещённые элементы",
        status="info",
        detail="Требуют визуальной проверки (vision-QA — Этап 6): " + "; ".join(items),
    )


def _aggregate(checks: list[QaCheck]) -> QaStatus:
    """Агрегатный статус: максимальная серьёзность среди pass/warn/fail."""
    rank = max((_RANK.get(c.status, 0) for c in checks), default=1)
    return {3: "fail", 2: "warn", 1: "pass"}.get(rank, "pass")  # type: ignore[return-value]


def build_qa_report(
    *,
    concept: CardConcept | None,
    template: MarketplaceTemplate,
    final_png: bytes | None,
    image_png: bytes | None,
    source_png: bytes | None = None,
    mask_png: bytes | None = None,
    mode: str | None = None,
) -> QaReport:
    """Собрать отчёт авто-QA по версии карточки (чистая функция).

    ``final_png`` — карточка с текстом [6] (предпочтительна для оценки размеров/фона/
    читаемости — её видит покупатель), ``image_png`` — изображение [5] без текста (для
    сверки товара с ``source_png`` по ``mask_png``). Хотя бы одно из изображений должно
    быть передано. Текстовые проверки выполняются, если задана концепция (есть блоки).
    """
    display_png = final_png or image_png
    if display_png is None:
        raise ValueError("Нет изображения для QA: не передан ни final_png, ни image_png")
    display = Image.open(io.BytesIO(display_png)).convert("RGB")
    width, height = display.size

    blocks = concept_to_render_blocks(concept, template) if concept else []

    checks: list[QaCheck] = [
        check_dimensions(width, height, template),
        check_text_size(blocks, height),
        check_text_contrast(blocks, display_png),
        check_product_fidelity(
            source_png=source_png, image_png=image_png, mask_png=mask_png, mode=mode
        ),
        check_forbidden_elements(concept),
    ]
    white = check_white_background(display_png, mask_png, template)
    if white is not None:
        checks.append(white)

    status = _aggregate(checks)
    n_fail = sum(1 for c in checks if c.status == "fail")
    n_warn = sum(1 for c in checks if c.status == "warn")
    if status == "fail":
        summary = (
            f"Провалено проверок: {n_fail}; предупреждений: {n_warn}. Карточку нужно доработать."
        )
    elif status == "warn":
        summary = f"Предупреждений: {n_warn}. Карточка пригодна, но есть замечания."
    else:
        summary = "Все автоматические проверки пройдены."

    return QaReport(
        status=status,
        summary=summary,
        checks=checks,
        width=width,
        height=height,
        template_key=template.key,
    )

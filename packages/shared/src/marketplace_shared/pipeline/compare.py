"""Сравнение подходов генерации изображения [5]: editing vs композитинг (задача Этапа 2).

Два уже реализованных режима стадии [5] (см. :mod:`marketplace_shared.pipeline.imagegen`)
по-разному рискуют главным инвариантом проекта — сохранением товара без искажений:

- **edit** — editing-модель правит фон по инструкции, товар остаётся «как есть» на её
  усмотрение (риск дрейфа формы/цвета/деталей);
- **composite** — товар вырезается стадией [4] и кладётся на сгенерированный фон 1:1
  (пиксели товара неизменны по построению — «gold standard» по сохранности).

Чтобы выбрать дефолтный режим (задача «Сравнение подходов на реальных товарах
заказчика, выбор дефолта»), нужен **измеримый** прогон обоих режимов на одних и тех же
фото с объективными метриками. Этот модуль провайдеро-независим: на вход приходят
готовые :class:`ImageProvider` и :class:`MattingProvider` (echo для офлайн-прогона,
hosted Gemini/Flux — для реального сравнения), фото товара и концепция карточки [3].

Здесь только чистая логика и оркестрация: метрики (:func:`compute_metrics`), прогон
каждого режима (:func:`run_edit_approach` / :func:`run_composite_approach`), сборка
отчёта (:func:`compare_product`) и его рендер в HTML (:func:`render_report_html`).
Загрузку фото с диска/MinIO и выбор провайдеров делает тонкий CLI
(``scripts/compare_approaches.py``). Финальный выбор дефолта остаётся за человеком —
харнесс лишь даёт ему сопоставимые цифры и картинки.
"""

from __future__ import annotations

import base64
import io
import time
from collections.abc import Sequence
from html import escape

import httpx
from PIL import Image, ImageChops, ImageStat
from pydantic import BaseModel, Field

from marketplace_shared.pipeline.concepts import CardConcept
from marketplace_shared.pipeline.imagegen import (
    composite_product_on_background,
    generate_card_background,
    generate_card_image,
)
from marketplace_shared.providers.base import ImageProvider, MattingProvider
from marketplace_shared.providers.contracts import (
    ImageRef,
    MattingRequest,
    Usage,
)

#: Имена режимов — совпадают с `mode` эндпоинта POST /cards/{id}/generate.
APPROACH_EDIT = "edit"
APPROACH_COMPOSITE = "composite"


# --------------------------------------------------------------------------- #
# Метрики (чистые функции на Pillow, без сети и без numpy/torch)
# --------------------------------------------------------------------------- #


class ImageMetrics(BaseModel):
    """Объективные метрики результата относительно исходного фото товара.

    Главный критерий проекта — сохранность товара (`product_fidelity`). Оба показателя
    нормированы в 0..1 и считаются по средней поканальной разнице пикселей в области
    маски товара (`product_*`) и вне её (`background_*`).
    """

    #: 1.0 — пиксели товара совпадают с оригиналом, 0.0 — полностью изменены.
    #: Для composite близко к 1.0 по построению; для edit показывает реальный дрейф.
    product_fidelity: float = Field(ge=0.0, le=1.0)
    #: 0.0 — фон не изменился, 1.0 — изменён максимально. Хотим высокое значение:
    #: смысл стадии [5] — поменять фон/сцену вокруг товара.
    background_change: float = Field(ge=0.0, le=1.0)
    width: int
    height: int
    #: Совпал ли размер результата с размером исходного фото (без масштабирования).
    size_matches_source: bool


def _mean_channel_diff(diff_l: Image.Image, mask_l: Image.Image | None) -> float:
    """Среднее значение L-изображения разницы (0..255) в области маски (или по всему кадру)."""
    stat = ImageStat.Stat(diff_l, mask_l) if mask_l is not None else ImageStat.Stat(diff_l)
    # Stat.mean — список по каналам; у "L" один канал.
    return stat.mean[0] if stat.mean else 0.0


def compute_metrics(
    *,
    source_png: bytes,
    result_png: bytes,
    mask_png: bytes,
) -> ImageMetrics:
    """Посчитать метрики сохранности товара и изменения фона (чистая функция).

    ``source_png`` — исходное фото товара, ``result_png`` — результат режима,
    ``mask_png`` — маска товара из стадии [4] (белое=товар). Результат при
    несовпадении размера масштабируется под исходник (с пометкой ``size_matches_source``).
    """
    source = Image.open(io.BytesIO(source_png)).convert("RGB")
    result = Image.open(io.BytesIO(result_png)).convert("RGB")
    mask = Image.open(io.BytesIO(mask_png)).convert("L")

    size_matches = result.size == source.size
    if not size_matches:
        result = result.resize(source.size)
    if mask.size != source.size:
        mask = mask.resize(source.size)

    diff = ImageChops.difference(source, result).convert("L")
    inverted_mask = ImageChops.invert(mask)

    product_diff = _mean_channel_diff(diff, mask)
    background_diff = _mean_channel_diff(diff, inverted_mask)

    return ImageMetrics(
        product_fidelity=round(1.0 - product_diff / 255.0, 4),
        background_change=round(background_diff / 255.0, 4),
        width=source.size[0],
        height=source.size[1],
        size_matches_source=size_matches,
    )


# --------------------------------------------------------------------------- #
# Прогон режимов
# --------------------------------------------------------------------------- #


class ApproachResult(BaseModel):
    """Результат одного режима стадии [5] на одном товаре."""

    approach: str
    #: Текст инструкции (edit) или промта фона (composite) — для трейсинга/отчёта.
    prompt: str
    metrics: ImageMetrics
    usage: Usage = Field(default_factory=Usage)
    #: Время прогона режима, сек (wall-clock) — для сравнения скорости.
    elapsed_seconds: float
    #: PNG-байты результата (в HTML встраиваются как data-URI; из JSON-дампа исключены).
    result_png: bytes = Field(default=b"", exclude=True, repr=False)


class ComparisonReport(BaseModel):
    """Сравнение всех режимов на одном товаре."""

    product_label: str
    approaches: list[ApproachResult]
    source_png: bytes = Field(default=b"", exclude=True, repr=False)
    mask_png: bytes = Field(default=b"", exclude=True, repr=False)


async def _resolve_bytes(ref: ImageRef) -> bytes:
    """Достать байты изображения из ImageRef: inline-данные или скачать по URL."""
    if ref.data is not None:
        return ref.data
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(ref.url)  # type: ignore[arg-type]  # url задан валидатором ImageRef
        response.raise_for_status()
    return response.content


async def run_edit_approach(
    image_provider: ImageProvider,
    *,
    source_png: bytes,
    mask_png: bytes,
    concept: CardConcept,
    references: Sequence[ImageRef] | None = None,
    brand_style: str | None = None,
    model: str | None = None,
    size: str | None = None,
    seed: int | None = None,
) -> ApproachResult:
    """Прогнать режим **edit**: editing-модель меняет фон, товар обязан сохраниться."""
    started = time.perf_counter()
    result, instruction = await generate_card_image(
        image_provider,
        product_photo=ImageRef(data=source_png),
        concept=concept,
        references=list(references or []),
        brand_style=brand_style,
        model=model,
        size=size,
        seed=seed,
    )
    elapsed = time.perf_counter() - started
    result_png = await _resolve_bytes(result.image)
    metrics = compute_metrics(source_png=source_png, result_png=result_png, mask_png=mask_png)
    return ApproachResult(
        approach=APPROACH_EDIT,
        prompt=instruction,
        metrics=metrics,
        usage=result.usage,
        elapsed_seconds=round(elapsed, 3),
        result_png=result_png,
    )


async def run_composite_approach(
    image_provider: ImageProvider,
    *,
    source_png: bytes,
    cutout_png: bytes,
    mask_png: bytes,
    concept: CardConcept,
    references: Sequence[ImageRef] | None = None,
    brand_style: str | None = None,
    model: str | None = None,
    size: str | None = None,
    seed: int | None = None,
) -> ApproachResult:
    """Прогнать режим **composite**: фон генерируется, вырез товара [4] кладётся 1:1."""
    started = time.perf_counter()
    bg_result, prompt = await generate_card_background(
        image_provider,
        concept,
        references=list(references or []),
        brand_style=brand_style,
        model=model,
        size=size,
        seed=seed,
    )
    background_png = await _resolve_bytes(bg_result.image)
    result_png = composite_product_on_background(background_png, cutout_png)
    elapsed = time.perf_counter() - started
    metrics = compute_metrics(source_png=source_png, result_png=result_png, mask_png=mask_png)
    return ApproachResult(
        approach=APPROACH_COMPOSITE,
        prompt=prompt,
        metrics=metrics,
        usage=bg_result.usage,
        elapsed_seconds=round(elapsed, 3),
        result_png=result_png,
    )


async def compare_product(
    *,
    product_label: str,
    source_png: bytes,
    concept: CardConcept,
    image_provider: ImageProvider,
    matting_provider: MattingProvider,
    references: Sequence[ImageRef] | None = None,
    brand_style: str | None = None,
    model: str | None = None,
    size: str | None = None,
    seed: int | None = None,
) -> ComparisonReport:
    """Сравнить оба режима стадии [5] на одном товаре по одной концепции.

    Маска товара строится один раз (стадия [4]) и используется обоими режимами:
    composite — для выреза, и оба — как область товара при подсчёте метрик. Так
    сравнение честное: одинаковая разметка «товар/фон» для обоих результатов.
    """
    matte = await matting_provider.remove_background(
        MattingRequest(image=ImageRef(data=source_png))
    )
    mask_png = await _resolve_bytes(matte.mask)
    if matte.cutout is None:
        raise ValueError(
            "MattingProvider не вернул вырез товара (cutout) — composite-режим невозможен"
        )
    cutout_png = await _resolve_bytes(matte.cutout)

    edit = await run_edit_approach(
        image_provider,
        source_png=source_png,
        mask_png=mask_png,
        concept=concept,
        references=references,
        brand_style=brand_style,
        model=model,
        size=size,
        seed=seed,
    )
    composite = await run_composite_approach(
        image_provider,
        source_png=source_png,
        cutout_png=cutout_png,
        mask_png=mask_png,
        concept=concept,
        references=references,
        brand_style=brand_style,
        model=model,
        size=size,
        seed=seed,
    )
    return ComparisonReport(
        product_label=product_label,
        approaches=[edit, composite],
        source_png=source_png,
        mask_png=mask_png,
    )


def recommend_default(reports: Sequence[ComparisonReport]) -> str:
    """Подсказать дефолтный режим по совокупности отчётов (НЕ окончательный выбор).

    Эвристика отражает приоритет проекта: сначала сохранность товара
    (`product_fidelity`), при сопоставимой сохранности — большее изменение фона.
    Возвращает человекочитаемую строку-рекомендацию; финальное решение — за человеком.
    """
    if not reports:
        return "Нет данных для рекомендации."

    wins = {APPROACH_EDIT: 0, APPROACH_COMPOSITE: 0}
    for report in reports:
        by_name = {a.approach: a for a in report.approaches}
        edit, composite = by_name.get(APPROACH_EDIT), by_name.get(APPROACH_COMPOSITE)
        if edit is None or composite is None:
            continue
        # Порог 0.01 — сохранность считается «сопоставимой», тогда решает изменение фона.
        if abs(edit.metrics.product_fidelity - composite.metrics.product_fidelity) <= 0.01:
            winner = (
                APPROACH_COMPOSITE
                if composite.metrics.background_change >= edit.metrics.background_change
                else APPROACH_EDIT
            )
        else:
            winner = (
                APPROACH_EDIT
                if edit.metrics.product_fidelity > composite.metrics.product_fidelity
                else APPROACH_COMPOSITE
            )
        wins[winner] += 1

    total = len(reports)
    leader = max(wins, key=lambda k: wins[k])
    return (
        f"Рекомендация (по сохранности товара, затем изменению фона): дефолт «{leader}» — "
        f"лидирует на {wins[leader]} из {total} товаров "
        f"(edit: {wins[APPROACH_EDIT]}, composite: {wins[APPROACH_COMPOSITE]}). "
        "Это подсказка по объективным метрикам — окончательный выбор за человеком "
        "после визуальной оценки отчёта."
    )


# --------------------------------------------------------------------------- #
# HTML-отчёт (чистая функция: байты → строка)
# --------------------------------------------------------------------------- #


def _data_uri(png: bytes) -> str:
    """PNG-байты → data-URI для встраивания в самодостаточный HTML-отчёт."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _fmt_usage(usage: Usage) -> str:
    parts: list[str] = []
    if usage.cost_usd is not None:
        parts.append(f"${usage.cost_usd:.4f}")
    if usage.input_tokens is not None or usage.output_tokens is not None:
        parts.append(f"ток. {usage.input_tokens or 0}/{usage.output_tokens or 0}")
    if usage.extra:
        parts.append(", ".join(f"{k}={v}" for k, v in usage.extra.items()))
    return escape(" · ".join(parts)) if parts else "—"


def _approach_cell(approach: ApproachResult) -> str:
    m = approach.metrics
    size_note = "" if m.size_matches_source else " <em>(масштабирован)</em>"
    return f"""
      <td class="cell">
        <div class="approach-name">{escape(approach.approach)}</div>
        <img src="{_data_uri(approach.result_png)}" alt="{escape(approach.approach)}"/>
        <table class="metrics">
          <tr><td>сохранность товара</td><td class="num">{m.product_fidelity:.3f}</td></tr>
          <tr><td>изменение фона</td><td class="num">{m.background_change:.3f}</td></tr>
          <tr><td>размер</td><td class="num">{m.width}×{m.height}{size_note}</td></tr>
          <tr><td>время, сек</td><td class="num">{approach.elapsed_seconds:.3f}</td></tr>
          <tr><td>расход</td><td class="num">{_fmt_usage(approach.usage)}</td></tr>
        </table>
        <details><summary>промт</summary><p class="prompt">{escape(approach.prompt)}</p></details>
      </td>"""


def render_report_html(
    reports: Sequence[ComparisonReport],
    *,
    title: str = "Сравнение подходов стадии [5]: edit vs composite",
    recommendation: str | None = None,
) -> str:
    """Собрать самодостаточный HTML-отчёт (картинки встроены как data-URI).

    Для каждого товара — строка: исходное фото и результаты режимов рядом, под каждым —
    метрики (сохранность товара, изменение фона, размер, время, расход) и промт.
    """
    rec = recommendation if recommendation is not None else recommend_default(reports)
    rows: list[str] = []
    for report in reports:
        cells = [
            f"""
      <td class="cell source">
        <div class="approach-name">оригинал</div>
        <img src="{_data_uri(report.source_png)}" alt="оригинал"/>
        <table class="metrics"><tr><td>маска товара [4]</td><td class="num">есть</td></tr></table>
      </td>"""
        ]
        cells.extend(_approach_cell(a) for a in report.approaches)
        rows.append(
            f'    <tr><th class="label">{escape(report.product_label)}</th>'
            + "".join(cells)
            + "</tr>"
        )

    style = """
      body { font-family: system-ui, sans-serif; margin: 24px; color: #1a1a1a;
             background: #fafafa; }
      h1 { font-size: 20px; }
      .rec { background: #fff6e5; border: 1px solid #f0c674; border-radius: 8px;
             padding: 12px 16px; margin: 16px 0; }
      table.grid { border-collapse: collapse; width: 100%; }
      table.grid > tbody > tr { border-bottom: 1px solid #e0e0e0; }
      th.label { text-align: left; vertical-align: top; padding: 12px 8px; width: 120px;
                 font-size: 13px; }
      td.cell { vertical-align: top; padding: 12px 8px; text-align: center; }
      td.cell img { max-width: 240px; max-height: 240px; border: 1px solid #ddd;
                    border-radius: 6px; background: #fff; }
      .approach-name { font-weight: 600; margin-bottom: 6px; }
      td.source .approach-name { color: #888; }
      table.metrics { margin: 8px auto 0; font-size: 12px; border-collapse: collapse; }
      table.metrics td { padding: 1px 8px; }
      table.metrics td.num { text-align: right; font-variant-numeric: tabular-nums; }
      .prompt { font-size: 11px; color: #555; max-width: 260px; text-align: left; }
      details { font-size: 12px; margin-top: 6px; }
    """
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"/>
<title>{escape(title)}</title><style>{style}</style></head>
<body>
  <h1>{escape(title)}</h1>
  <div class="rec">{escape(rec)}</div>
  <table class="grid"><tbody>
{chr(10).join(rows)}
  </tbody></table>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Демонстрационная концепция — для офлайн-прогона харнесса без файла концепции
# --------------------------------------------------------------------------- #


def demo_concept() -> CardConcept:
    """Простейшая концепция карточки [3] для офлайн-прогона сравнения без внешних данных."""
    return CardConcept(
        role="hero",
        title="Главная карточка",
        composition="Товар крупно по центру, воздух вокруг, акцент на форме.",
        product_placement="Центр кадра, фронтальный ракурс, крупный масштаб.",
        background="Чистая студийная сцена с мягким градиентом и лёгкой тенью под товаром.",
        color_palette=["#f5f5f5", "#e8e2d8", "#c9a36a"],
        must_have=["товар без искажений", "чистый фон"],
        must_not_have=["лишние предметы", "текст на фоне"],
    )

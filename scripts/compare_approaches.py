"""CLI-харнесс сравнения режимов стадии [5]: editing vs композитинг.

Задача Этапа 2 «Сравнение подходов на реальных товарах заказчика, выбор дефолта».
Прогоняет оба режима генерации изображения на заданных фото товаров по одной
концепции карточки [3] и собирает самодостаточный HTML-отчёт с метриками
(сохранность товара, изменение фона, размер, время, расход) — чтобы человек выбрал
дефолтный режим по сопоставимым цифрам и картинкам.

Провайдеры берутся из реестра по конфигурации окружения (`IMAGE_PROVIDER`,
`MATTING_PROVIDER`). По умолчанию это офлайн-`echo`/`simple` — харнесс гоняется без
сети и ключей (демонстрация механики). Реальное сравнение качества:
``IMAGE_PROVIDER=gemini GEMINI_API_KEY=... uv run python scripts/compare_approaches.py ...``.

Примеры:
    # офлайн-демо на любых PNG/JPG (echo): сразу видно механику и отчёт
    uv run python scripts/compare_approaches.py --photo photo1.jpg --photo photo2.png

    # реальное сравнение на папке фото заказчика по их концепции
    IMAGE_PROVIDER=gemini GEMINI_API_KEY=... \\
      uv run python scripts/compare_approaches.py \\
        --photos-dir ./products --concept concept.json --out ./out --size 1024x1024
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from pathlib import Path

from marketplace_shared.pipeline.compare import (
    ComparisonReport,
    compare_product,
    demo_concept,
    recommend_default,
    render_report_html,
)
from marketplace_shared.pipeline.concepts import CardConcept
from marketplace_shared.providers.config import get_provider_settings
from marketplace_shared.providers.registry import (
    get_image_provider,
    get_matting_provider,
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _collect_photos(args: argparse.Namespace) -> list[Path]:
    """Собрать пути к фото из --photo и --photos-dir, оставив только изображения."""
    paths: list[Path] = [Path(p) for p in (args.photo or [])]
    if args.photos_dir:
        directory = Path(args.photos_dir)
        if not directory.is_dir():
            raise SystemExit(f"--photos-dir: не каталог: {directory}")
        paths.extend(sorted(p for p in directory.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES))
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise SystemExit("Не найдены файлы: " + ", ".join(str(p) for p in missing))
    if not paths:
        raise SystemExit("Не задано ни одного фото (--photo / --photos-dir).")
    return paths


def _load_concept(path_str: str | None) -> CardConcept:
    """Загрузить концепцию карточки [3] из JSON (CardConcept или CardSetConcepts) или взять демо."""
    if not path_str:
        return demo_concept()
    data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cards" in data:  # CardSetConcepts → первая карточка
        cards = data["cards"]
        if not cards:
            raise SystemExit(f"--concept: в наборе нет карточек: {path_str}")
        data = cards[0]
    return CardConcept.model_validate(data)


def _print_summary(reports: list[ComparisonReport]) -> None:
    """Печать компактной таблицы метрик в stdout."""
    header = f"{'товар':<24} {'режим':<10} {'товар↑':>8} {'фон↑':>7} {'сек':>7}"
    print(header)
    print("-" * len(header))
    for report in reports:
        for approach in report.approaches:
            m = approach.metrics
            label = report.product_label[:23]
            print(
                f"{label:<24} {approach.approach:<10} "
                f"{m.product_fidelity:>8.3f} {m.background_change:>7.3f} "
                f"{approach.elapsed_seconds:>7.3f}"
            )


async def _run(args: argparse.Namespace) -> int:
    settings = get_provider_settings()
    image_provider = get_image_provider(settings)
    matting_provider = get_matting_provider(settings)
    print(
        f"IMAGE_PROVIDER={settings.image_provider} (model={settings.image_model}), "
        f"MATTING_PROVIDER={settings.matting_provider}",
        file=sys.stderr,
    )

    concept = _load_concept(args.concept)
    photos = _collect_photos(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    reports: list[ComparisonReport] = []
    for photo in photos:
        print(f"→ {photo.name}", file=sys.stderr)
        report = await compare_product(
            product_label=photo.stem,
            source_png=photo.read_bytes(),
            concept=concept,
            image_provider=image_provider,
            matting_provider=matting_provider,
            brand_style=args.brand_style,
            size=args.size,
            seed=args.seed,
        )
        reports.append(report)
        # Сохраняем результаты режимов рядом с отчётом для ручного просмотра.
        for approach in report.approaches:
            (out_dir / f"{photo.stem}.{approach.approach}.png").write_bytes(approach.result_png)

    recommendation = recommend_default(reports)
    html = render_report_html(reports, recommendation=recommendation)
    report_path = out_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")

    print()
    _print_summary(reports)
    print()
    print(recommendation)
    print(f"\nОтчёт: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Сравнение режимов стадии [5] (edit vs composite) на фото товаров."
    )
    parser.add_argument(
        "--photo", action="append", metavar="PATH", help="Фото товара (можно повторять)."
    )
    parser.add_argument("--photos-dir", metavar="DIR", help="Каталог с фото товаров.")
    parser.add_argument(
        "--concept",
        metavar="JSON",
        help="JSON концепции [3] (CardConcept или CardSetConcepts). Без него — демо-концепция.",
    )
    parser.add_argument("--out", default="compare_out", metavar="DIR", help="Каталог результата.")
    parser.add_argument("--size", metavar="WxH", help="Размер генерации, напр. 1024x1024.")
    parser.add_argument("--seed", type=int, help="Seed генерации (для воспроизводимости).")
    parser.add_argument("--brand-style", metavar="TEXT", help="Описание стиля бренда.")
    args = parser.parse_args(argv)
    # Windows-консоль по умолчанию cp1251 — стрелки/символы отчёта требуют utf-8.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

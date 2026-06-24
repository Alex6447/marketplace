"""Matting-провайдеры — удаление фона и маска товара (стадия [4]).

`SimpleMattingProvider` — офлайн-реализация без GPU и без весов моделей: кеинг по
цвету фона (оценивается по углам кадра) средствами Pillow. Работает на CPU,
детерминирована и годится для API-first MVP, когда товар снят на однотонном фоне
(типичный кейс маркетплейсов). Это осознанный fallback: BiRefNet/RMBG-2.0/SAM2 —
SOTA по сложным краям (волосы, стекло, упаковка) — подключаются как локальные модели
на Этапе 6 (docs_marketplace/plan.md, разделы 4 и 7) через тот же интерфейс `MattingProvider`.

Логика разнесена на чистую функцию `compute_matte` (без сети/IO — удобно тестировать)
и тонкую async-обёртку провайдера, которая лишь достаёт байты изображения.
"""

from __future__ import annotations

import io
from typing import Any

import httpx
from PIL import Image, ImageChops, ImageFilter

from .base import MattingProvider
from .contracts import ImageRef, MattingRequest, MattingResult, Usage

#: Порог отделения товара от фона: евклидоподобная разница яркости diff-изображения
#: (0..255). Ниже порога — фон (прозрачно), выше — товар. Подобран под однотонные фоны.
DEFAULT_THRESHOLD = 32

#: Размер угловой выборки (в долях стороны) для оценки цвета фона.
_CORNER_FRACTION = 0.06


def _estimate_bg_color(image: Image.Image) -> tuple[int, int, int]:
    """Оценить цвет фона по четырём углам кадра (усреднение угловых патчей)."""
    width, height = image.size
    cw = max(1, int(width * _CORNER_FRACTION))
    ch = max(1, int(height * _CORNER_FRACTION))
    boxes = (
        (0, 0, cw, ch),
        (width - cw, 0, width, ch),
        (0, height - ch, cw, height),
        (width - cw, height - ch, width, height),
    )
    rs, gs, bs = [], [], []
    for box in boxes:
        # resize((1, 1)) усредняет патч до одного пикселя на C-уровне.
        r, g, b = image.crop(box).resize((1, 1)).getpixel((0, 0))[:3]
        rs.append(r)
        gs.append(g)
        bs.append(b)
    n = len(boxes)
    return (sum(rs) // n, sum(gs) // n, sum(bs) // n)


def compute_matte(image_bytes: bytes, *, threshold: int = DEFAULT_THRESHOLD) -> tuple[bytes, bytes]:
    """Построить маску товара и вырез с прозрачным фоном (PNG-байты).

    Чистая, детерминированная: цвет фона берётся из углов, маска — порог по разнице
    с фоном, лёгкое медианное сглаживание убирает одиночные артефакты. Возвращает
    ``(mask_png, cutout_png)``: маска — grayscale (белое=товар), вырез — RGBA.
    """
    rgb = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    bg_color = _estimate_bg_color(rgb)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg_color)).convert("L")
    mask = diff.point(lambda v: 255 if v >= threshold else 0).convert("L")
    # Медианный фильтр сглаживает «соль-перец» на границе товар/фон.
    mask = mask.filter(ImageFilter.MedianFilter(size=3))

    cutout = rgb.convert("RGBA")
    cutout.putalpha(mask)

    mask_buf, cutout_buf = io.BytesIO(), io.BytesIO()
    mask.save(mask_buf, format="PNG")
    cutout.save(cutout_buf, format="PNG")
    return mask_buf.getvalue(), cutout_buf.getvalue()


class SimpleMattingProvider(MattingProvider):
    """Удаление фона кеингом по цвету (Pillow, CPU, без весов) — MVP-реализация [4]."""

    name = "simple"

    def __init__(self, *, model: str | None = None, threshold: int = DEFAULT_THRESHOLD) -> None:
        self._model = model or "simple-matte"
        self._threshold = threshold

    async def _resolve(self, ref: ImageRef) -> bytes:
        """Получить байты изображения: из inline-данных или скачать по presigned-URL."""
        if ref.data is not None:
            return ref.data
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ref.url)  # type: ignore[arg-type]  # url задан (валидатор ImageRef)
            response.raise_for_status()
        return response.content

    async def remove_background(self, request: MattingRequest) -> MattingResult:
        image_bytes = await self._resolve(request.image)
        mask_png, cutout_png = compute_matte(image_bytes, threshold=self._threshold)
        raw: dict[str, Any] = {"threshold": self._threshold}
        return MattingResult(
            mask=ImageRef(data=mask_png, media_type="image/png"),
            cutout=ImageRef(data=cutout_png, media_type="image/png"),
            provider=self.name,
            model=self._model,
            usage=Usage(extra={"images": 1}),
            raw=raw,
        )

"""Стадия [4] — подготовка ассета: удаление фона и маска товара.

См. docs_marketplace/plan.md, раздел 3 (стадия [4]) и раздел 4 (BiRefNet/RMBG-2.0/SAM2). Берёт
фото товара и через :class:`MattingProvider` строит маску товара и вырез с
прозрачным фоном. Маска нужна стадии [5] (композитинг — вставка товара 1:1) и QA
(стадия [7] — проверка, что товар на месте и не искажён).

Логика провайдеро-независима: на вход — готовый :class:`MattingProvider` (офлайн
`simple` на Pillow или локальные BiRefNet/SAM2 на Этапе 6). Здесь — тонкая обёртка с
валидацией результата; вся работа с пикселями инкапсулирована в провайдере.
"""

from __future__ import annotations

from marketplace_shared.providers.base import MattingProvider
from marketplace_shared.providers.contracts import ImageRef, MattingRequest, MattingResult
from marketplace_shared.providers.errors import ProviderError


async def prepare_asset(
    provider: MattingProvider, image: ImageRef, *, model: str | None = None
) -> MattingResult:
    """Удалить фон и построить маску товара для фото.

    Возвращает :class:`MattingResult` (маска + вырез). Бросает :class:`ProviderError`,
    если провайдер не вернул маску.
    """
    result = await provider.remove_background(MattingRequest(image=image, model=model))
    if result.mask.data is None and result.mask.url is None:
        raise ProviderError(
            f"matting-провайдер {result.provider!r} не вернул маску товара (стадия [4])"
        )
    return result

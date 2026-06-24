"""Pydantic-контракты провайдер-слоя — единый язык запросов/ответов.

Эти модели не зависят от конкретного провайдера (hosted или local): пайплайн
оперирует ими, а реализации `LLMProvider`/`ImageProvider` транслируют их в вызовы
своих SDK и обратно. Это и есть точка провайдеро-независимости (docs_marketplace/plan.md, 4.1).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Usage(BaseModel):
    """Учёт расхода ресурсов на вызов — для наблюдаемости и оценки стоимости.

    Поля опциональны: разные провайдеры отдают разный набор метрик. `extra` — место
    для провайдеро-специфичных счётчиков (кредиты, число шагов и т.п.).
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #

Role = Literal["system", "user", "assistant"]


class LLMMessage(BaseModel):
    """Одно сообщение диалога."""

    role: Role
    content: str


class LLMRequest(BaseModel):
    """Запрос к LLM.

    Если задан `response_schema` (JSON Schema), провайдер обязан вернуть структуру,
    валидную по ней (через tool-use / JSON-mode), и положить её в `LLMResponse.data`.
    Это контракт стадий [2] (идеи) и [3] (визуальная концепция).
    """

    messages: list[LLMMessage]
    model: str | None = None  # None → дефолтная модель провайдера
    max_tokens: int = 2048
    temperature: float = 1.0
    response_schema: dict[str, Any] | None = None


class LLMResponse(BaseModel):
    """Ответ LLM. `data` заполняется, когда в запросе был `response_schema`."""

    text: str = ""
    data: dict[str, Any] | None = None
    provider: str
    model: str
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] | None = None  # «сырой» ответ провайдера (для трейсинга)


# --------------------------------------------------------------------------- #
# Image
# --------------------------------------------------------------------------- #


class ImageRef(BaseModel):
    """Ссылка на изображение: inline-байты ИЛИ URL (ровно одно из полей).

    В пайплайне изображения живут в MinIO/S3, поэтому обычный случай — `url`
    (в т.ч. presigned). `data` — для inline-передачи небольших картинок.
    """

    data: bytes | None = None
    url: str | None = None
    media_type: str = "image/png"

    @model_validator(mode="after")
    def _exactly_one_source(self) -> ImageRef:
        if (self.data is None) == (self.url is None):
            raise ValueError("ImageRef: задайте ровно одно из полей — data или url")
        return self


class ImageEditRequest(BaseModel):
    """Editing по инструкции: «оставь товар, измени фон/сцену» (основной режим [5]).

    `image` — исходное фото товара (его и нужно сохранить без искажений),
    `references` — опциональные референсы сцены/стиля.
    """

    instruction: str
    image: ImageRef
    references: list[ImageRef] = Field(default_factory=list)
    model: str | None = None
    size: str | None = None  # напр. "1024x1024"
    seed: int | None = None


class ImageGenRequest(BaseModel):
    """Генерация изображения с нуля по промту — например, фон/сцена для композитинга."""

    prompt: str
    references: list[ImageRef] = Field(default_factory=list)
    model: str | None = None
    size: str | None = None
    seed: int | None = None


class ImageResult(BaseModel):
    """Результат image-провайдера."""

    image: ImageRef
    provider: str
    model: str
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Matting (стадия [4] — удаление фона / маска товара)
# --------------------------------------------------------------------------- #


class MattingRequest(BaseModel):
    """Удаление фона и построение маски товара (стадия [4], BiRefNet/SAM2/простой кеинг).

    `image` — исходное фото товара. Результат — маска товара (и вырез с прозрачным
    фоном), которые использует стадия [5] (композитинг) и QA (стадия [7]).
    """

    image: ImageRef
    model: str | None = None


class MattingResult(BaseModel):
    """Результат matting: маска товара и (опц.) вырез с прозрачным фоном."""

    #: Маска товара: grayscale PNG, белое (255) — товар, чёрное (0) — фон.
    mask: ImageRef
    #: Вырез товара: RGBA PNG с прозрачным фоном (для композитинга стадии [5]).
    cutout: ImageRef | None = None
    provider: str
    model: str
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] | None = None

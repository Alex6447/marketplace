"""Стадии пайплайна генерации карточек (docs/plan.md, раздел 3).

Здесь живёт провайдеро-независимая бизнес-логика стадий: построение запроса к
модели, разбор и валидация результата в Pydantic-контракты. Стадии не знают, какой
провайдер их обслуживает (hosted/local) и кто их вызывает — синхронный API (Этап 1)
или Celery-воркер (Этап 2): на вход им передаётся готовый :class:`LLMProvider`/
:class:`ImageProvider`.

Стадия [2] «генерация идей» — в :mod:`marketplace_shared.pipeline.ideas`.
Стадия [3] «визуальные концепции» — в :mod:`marketplace_shared.pipeline.concepts`.
Стадия [4] «подготовка ассета» — в :mod:`marketplace_shared.pipeline.assets_prep`.
Стадия [5] «генерация изображения» — в :mod:`marketplace_shared.pipeline.imagegen`.
"""

from __future__ import annotations

from .assets_prep import prepare_asset
from .cache import (
    PipelineSettings,
    StageCache,
    artifact_key,
    blob_digest,
    get_pipeline_settings,
    stage_digest,
)
from .concepts import (
    CardConcept,
    CardSetConcepts,
    TextBlock,
    build_concepts_request,
    generate_concepts,
)
from .feedback import (
    ChangeOperation,
    FeedbackActionType,
    FeedbackChange,
    FeedbackInput,
    FeedbackStage,
    ParsedFeedback,
    build_feedback_request,
    parse_feedback,
)
from .ideas import (
    IdeaSlide,
    ProductBrief,
    ProductIdeas,
    build_ideas_request,
    generate_ideas,
)
from .imagegen import (
    build_background_prompt,
    build_edit_instruction,
    composite_product_on_background,
    generate_card_background,
    generate_card_image,
)
from .textoverlay import (
    build_card_render_request,
    concept_to_render_blocks,
    render_card_text,
)

__all__ = [
    # стадия [2]
    "ProductBrief",
    "IdeaSlide",
    "ProductIdeas",
    "build_ideas_request",
    "generate_ideas",
    # стадия [3]
    "TextBlock",
    "CardConcept",
    "CardSetConcepts",
    "build_concepts_request",
    "generate_concepts",
    # стадия [4]
    "prepare_asset",
    # стадия [5]
    "build_edit_instruction",
    "generate_card_image",
    "build_background_prompt",
    "generate_card_background",
    "composite_product_on_background",
    # стадия [6] — наложение текста концепции
    "concept_to_render_blocks",
    "build_card_render_request",
    "render_card_text",
    # стадия [9] — разбор фидбэка
    "FeedbackInput",
    "ParsedFeedback",
    "FeedbackStage",
    "FeedbackActionType",
    "FeedbackChange",
    "ChangeOperation",
    "build_feedback_request",
    "parse_feedback",
    # контент-адресуемый кэш стадий
    "PipelineSettings",
    "get_pipeline_settings",
    "StageCache",
    "stage_digest",
    "artifact_key",
    "blob_digest",
]

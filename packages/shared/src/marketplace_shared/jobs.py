"""Константы фоновых задач (таблица :class:`Job`, docs/plan.md, разделы 5–6).

Чистый модуль без зависимостей: общий словарь статусов и типов задач для API
(создаёт Job и ставит задачу в очередь) и воркера (исполняет и обновляет статус).
Так обе стороны согласованы без импортов друг друга и без celery в shared.
"""

from __future__ import annotations

# --- Статусы задачи -------------------------------------------------------- #
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILURE = "failure"

#: Терминальные статусы — на них SSE-поток завершается.
TERMINAL_STATUSES = frozenset({JOB_SUCCESS, JOB_FAILURE})

# --- Типы задач (значение Job.type) ---------------------------------------- #
#: Стадия [4] — удаление фона и маска товара.
JOB_ASSET_MATTING = "asset_matting"
#: Стадия [5] — генерация изображения одной карточки (edit/composite).
JOB_CARD_IMAGE = "card_image"
#: Стадия [5] для всего набора карточек (Celery group по карточкам).
JOB_CARD_SET_IMAGES = "card_set_images"
#: Стадия [6] — наложение текста концепции на изображение версии карточки.
JOB_CARD_TEXT = "card_text"
#: Перегенерация адресуемой стадии по разобранному фидбэку (стадия [9] → [3]/[5]/[6]).
JOB_FEEDBACK_REGEN = "feedback_regen"

#: Имена Celery-задач (общий контракт API↔worker; API шлёт их по имени, без импорта).
TASK_ASSET_MATTING = "marketplace.asset_matting"
TASK_CARD_IMAGE = "marketplace.card_image"
TASK_CARD_TEXT = "marketplace.card_text"
#: Перегенерация адресуемой стадии по фидбэку (стадия [9] → [3]/[5]/[6]).
TASK_FEEDBACK_REGEN = "marketplace.feedback_regen"
#: Финализатор chord'а набора карточек — отмечает родительскую задачу успехом.
TASK_CARD_SET_FINALIZE = "marketplace.card_set_finalize"

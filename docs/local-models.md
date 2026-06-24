# Локальные модели: версионирование и монтирование (Этап 6)

Фиксация версий весов локальных моделей (закрытый контур / приватность / нулевая плата
за генерацию) и стратегия их монтирования как тома с кэшем. Дополняет
[plan.md](plan.md) (раздел 4.1, Этап 6) и провайдер-абстракции
`marketplace_shared.providers` (`comfyui`, `ollama`).

> **Зачем фиксировать.** Главный риск проекта — сохранение товара без искажений —
> чувствителен к версии модели: смена весов меняет поведение пайплайна. Поэтому версии
> моделей **пинуются** (источник + точное имя файла + размер + SHA256), а сами веса
> монтируются как том и **кэшируются** (скачиваются один раз, переживают пересборку
> контейнеров).

## 1. Веса под ComfyUI (стадии [4] matting, [5] image)

Сервер: ComfyUI (`IMAGE_PROVIDER='comfyui'`, `MATTING_PROVIDER='birefnet'`). Корень
весов — `…/ComfyUI/models` (на dev-стенде `D:\AI\ComfyUI\models`).

| Компонент | Файл (целевой путь от `models/`) | Источник (HuggingFace) | Размер, байт | SHA256 |
|-----------|----------------------------------|------------------------|--------------|--------|
| Flux.1 Kontext dev (UNet, GGUF Q4_K_M) | `unet/flux1-kontext-dev-Q4_K_M.gguf` | `QuantStack/FLUX.1-Kontext-dev-GGUF` | 6 931 817 760 | `ebd4e92c44c47f104ad64e4353692f37addf06eb99420c9b459334d871c8b750` |
| T5-xxl encoder (GGUF Q5_K_M) | `text_encoders/t5-v1_1-xxl-encoder-Q5_K_M.gguf` | `city96/t5-v1_1-xxl-encoder-gguf` | 3 386 856 640 | `b51cbb10b1a7aac6dd1c3b62f0ed908bfd06e0b42d2f3577d43e061361f51dae` |
| CLIP-L (text encoder) | `text_encoders/clip_l.safetensors` | `comfyanonymous/flux_text_encoders` | 246 144 152 | `660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd` |
| Flux VAE (автоэнкодер) | `vae/ae.safetensors` | `Comfy-Org/Lumina_Image_2.0_Repackaged` (`split_files/vae/ae.safetensors`, ungated) | 335 304 388 | `afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38` |
| BiRefNet `General` (matting [4]) | `BiRefNet/General.safetensors` | `ZhengPeng7/BiRefNet` (авто-скачивает нода `ComfyUI_BiRefNet_ll`) | 444 473 596 | `9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154` |

Кастом-ноды ComfyUI (тоже фиксируются — pin по git-коммиту в проде):
`city96/ComfyUI-GGUF` (загрузка GGUF), `lldacing/ComfyUI_BiRefNet_ll` (matting).

## 2. Веса под Ollama (стадии [2] идеи, [3] концепции, [9] фидбэк)

Сервер: Ollama (`LLM_PROVIDER='ollama'`). Корень — каталог моделей Ollama
(`%USERPROFILE%\.ollama\models` / `~/.ollama/models`); пин по дайджесту манифеста.

| Модель | Параметры | Квант | Размер | Дайджест (manifest) |
|--------|-----------|-------|--------|---------------------|
| `gemma4:latest` (дефолт стенда, оптимум под 12 ГБ) | 8.0B | Q4_K_M | 9.6 ГБ | `sha256:c6eb396dbd5992bb…` |
| `gemma4:26b` | 25.8B | Q4_K_M | 18.0 ГБ | `sha256:5571076f3d700504…` |
| `gpt-oss:20b` | 20.9B | MXFP4 | 13.8 ГБ | `sha256:aa4295ac10c3afb6…` |

Пин версии в проде: тег модели Ollama не неизменяем (`:latest` плывёт) — для
воспроизводимости фиксировать **дайджест** (`ollama run gemma4@sha256:<digest>`) либо
держать собственный приватный реестр/Modelfile.

## 3. Монтирование (том) и кэш

Веса **не кладутся в образ** (десятки ГБ) — они монтируются как именованный том и
кэшируются между пересборками:

```yaml
# фрагмент docker-compose для local/hybrid-режима (Этап 7)
services:
  comfyui:
    # образ с ComfyUI + кастом-ноды (GGUF, BiRefNet)
    volumes:
      - comfyui-models:/app/ComfyUI/models   # веса Flux/T5/CLIP/VAE/BiRefNet
    # GPU: deploy.resources.reservations.devices (nvidia)
  ollama:
    image: ollama/ollama
    volumes:
      - ollama-models:/root/.ollama          # веса LLM
volumes:
  comfyui-models:   # переживает пересборку/обновление образов
  ollama-models:
```

- **Кэш:** том сохраняет уже скачанные веса; повторная установка/обновление образов их
  не перекачивает. BiRefNet и модели Ollama докачиваются в том при первом обращении.
- **Версионирование:** при обновлении модели — менять имя файла/тег и **обновлять эту
  таблицу** (размер + SHA256). Прод фиксирует конкретные версии, dev может обновлять.
- **Проверка целостности** скачанных весов ComfyUI против пинов:

```bash
cd "<ComfyUI>/models"
sha256sum unet/flux1-kontext-dev-Q4_K_M.gguf \
          text_encoders/t5-v1_1-xxl-encoder-Q5_K_M.gguf \
          text_encoders/clip_l.safetensors \
          vae/ae.safetensors \
          BiRefNet/General.safetensors
# сверить с колонкой SHA256 выше
```

Развёртывание dev-стенда и грабли Windows — см. провайдеры `comfyui.py`/`ollama.py`
и заметки в [plan.md](plan.md) (Этап 6).

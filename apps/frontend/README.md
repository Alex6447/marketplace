# apps/frontend — SPA-дашборд менеджера

React + TypeScript + Vite. Внутренний дашборд: создание проекта, загрузка товара,
просмотр идей/концепций, запуск генерации, просмотр версий и ввод текстового фидбэка.
Серверное состояние — TanStack Query, UI-кит — shadcn/ui, прогресс — через SSE.

## Стек и структура

- **Vite + React 18 + TypeScript** — `vite.config.ts`, `tsconfig*.json`.
- **TanStack Query** — клиент в `src/main.tsx`, запросы в `src/lib/api.ts`.
- **shadcn/ui** — Tailwind (`tailwind.config.ts`, `src/index.css` с CSS-переменными),
  `components.json`, утилита `src/lib/utils.ts`, компоненты в `src/components/ui/`.
- **Линтеры** — ESLint flat config (`eslint.config.js`) + Prettier (`.prettierrc.json`).
- Алиас `@/*` → `src/*`.

## Команды (из этой папки)

- `pnpm install` — установить зависимости (из корня репо — весь pnpm-воркспейс).
- `pnpm dev` — dev-сервер Vite на `127.0.0.1:5173`; `/api` и `/healthz` проксируются
  на FastAPI (`127.0.0.1:8000`).
- `pnpm lint` — ESLint; `pnpm format` / `pnpm format:check` — Prettier.
- `pnpm build` — типчек (`tsc -b`) + production-сборка в `dist/`.

> ⚠️ Лок-файл `pnpm-lock.yaml` (в корне) нужно один раз перегенерировать через
> `pnpm install` на машине с доступом к реестру npm, затем зафиксировать в гит.
> В production статика раздаётся nginx (без отдельного Node-сервера).

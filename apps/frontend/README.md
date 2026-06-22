# apps/frontend — SPA-дашборд менеджера

React + TypeScript + Vite. Внутренний дашборд: создание проекта, загрузка товара,
просмотр идей/концепций, запуск генерации, просмотр версий и ввод текстового фидбэка.
Серверное состояние — TanStack Query, UI-кит — shadcn/ui, прогресс — через SSE.

> Подключён к pnpm-воркспейсу (`package.json` пакета `@marketplace/frontend` на месте).
> Полный каркас (Vite + React + TanStack Query + shadcn/ui) и линтеры добавляются
> на пункте Этапа 0 «Каркас FastAPI + React» ([docs/plan.md](../../docs/plan.md), раздел 7).
> В production статика раздаётся nginx (без отдельного Node-сервера).

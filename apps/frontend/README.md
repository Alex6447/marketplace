# apps/frontend — SPA-дашборд менеджера

React + TypeScript + Vite. Внутренний дашборд: создание проекта, загрузка товара,
просмотр идей/концепций, запуск генерации, просмотр версий и ввод текстового фидбэка.
Серверное состояние — TanStack Query, UI-кит — shadcn/ui, прогресс — через SSE.

> Каркас (Vite + TanStack Query + shadcn/ui) и линтеры (`pnpm`) добавляются на пункте
> Этапа 0 «Каркас FastAPI + React» ([docs/plan.md](../../docs/plan.md), раздел 7).
> В production статика раздаётся nginx (без отдельного Node-сервера).

"""CRUD-роутер проектов (docs/plan.md, раздел 6).

Проект — верхнеуровневая единица работы. Здесь — создание, список и чтение
одного проекта. Товары проекта обслуживает роутер `products`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketplace_api.schemas import ProjectCreate, ProjectRead
from marketplace_shared.db import Project, get_session

router = APIRouter(prefix="/projects", tags=["projects"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, session: SessionDep) -> Project:
    """Создать проект."""
    project = Project(name=payload.name, brand_style=payload.brand_style)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
async def list_projects(session: SessionDep) -> list[Project]:
    """Список проектов (свежие — сверху)."""
    result = await session.scalars(select(Project).order_by(Project.created_at.desc()))
    return list(result.all())


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, session: SessionDep) -> Project:
    """Получить проект по id (404, если не найден)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return project

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FolderPlus, Layers, Plus } from "lucide-react";
import { useState, type ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorRow, LoadingRow, Spinner } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, createProject, listProjects, type Project } from "@/lib/api";
import { href, navigate } from "@/lib/router";

export function ProjectsView() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: listProjects });

  return (
    <AppShell crumbs={[{ label: "проекты" }]}>
      <div className="mb-9 max-w-2xl animate-rise">
        <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">
          Студия генерации
          <br />
          <span className="text-primary">карточек товара</span>
        </h1>
        <p className="mt-4 text-sm leading-relaxed text-muted-foreground sm:text-base">
          Проект → товар → идеи → концепции. Товар берётся с реального фото и сохраняется без
          искажений; текст накладывается отдельным детерминированным этапом.
        </p>
      </div>
      <div className="grid gap-8 lg:grid-cols-[1fr_22rem]">
        <section className="order-2 lg:order-1">
          <SectionHeading numeral="01" title="Проекты" caption="Бренды и заказы" />
          {projects.isLoading ? (
            <LoadingRow />
          ) : projects.isError ? (
            <ErrorRow message={(projects.error as Error).message} />
          ) : projects.data && projects.data.length > 0 ? (
            <ul className="grid gap-3 sm:grid-cols-2">
              {projects.data.map((p, i) => (
                <ProjectCard key={p.id} project={p} index={i} />
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={Layers}
              title="Пока нет проектов"
              description="Создайте первый проект справа — это бренд или заказ, внутри которого живут товары и комплекты карточек."
            />
          )}
        </section>

        <aside className="order-1 lg:order-2">
          <CreateProjectPanel />
        </aside>
      </div>
    </AppShell>
  );
}

function ProjectCard({ project, index }: { project: Project; index: number }) {
  return (
    <li className="animate-rise" style={{ animationDelay: `${index * 50}ms` }}>
      <a
        href={href({ name: "project", id: project.id })}
        onClick={(e) => {
          e.preventDefault();
          navigate({ name: "project", id: project.id });
        }}
        className="group block"
      >
        <Panel className="h-full p-5 transition-colors hover:border-primary/50">
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-display text-lg leading-tight">{project.name}</h3>
            <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
          </div>
          {project.brand_style ? (
            <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{project.brand_style}</p>
          ) : (
            <p className="mt-2 text-sm italic text-muted-foreground/60">стиль бренда не задан</p>
          )}
          <p className="mt-4 font-mono text-[0.66rem] uppercase tracking-[0.12em] text-muted-foreground/70">
            {new Date(project.created_at).toLocaleDateString("ru-RU", {
              day: "2-digit",
              month: "short",
              year: "numeric",
            })}
          </p>
        </Panel>
      </a>
    </li>
  );
}

function CreateProjectPanel() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [brandStyle, setBrandStyle] = useState("");

  const mutation = useMutation({
    mutationFn: () => createProject({ name: name.trim(), brand_style: brandStyle.trim() || null }),
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate({ name: "project", id: project.id });
    },
  });

  return (
    <Panel className="sticky top-24 p-5">
      <div className="mb-4 flex items-center gap-2">
        <FolderPlus className="h-4 w-4 text-primary" />
        <h2 className="font-display text-base">Новый проект</h2>
      </div>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) mutation.mutate();
        }}
      >
        <Field label="Название" htmlFor="project-name">
          <Input
            id="project-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Напр. Спортивный бренд Atlas"
            maxLength={255}
            required
          />
        </Field>
        <Field label="Стиль бренда" hint="необязательно" htmlFor="project-brand">
          <Textarea
            id="project-brand"
            value={brandStyle}
            onChange={(e) => setBrandStyle(e.target.value)}
            placeholder="Тон, цвета, визуальные правила. Напр.: минимализм, тёплые тона, без агрессии."
          />
        </Field>
        {mutation.isError ? <ErrorRow message={describeError(mutation.error)} /> : null}
        <Button type="submit" className="w-full" disabled={!name.trim() || mutation.isPending}>
          {mutation.isPending ? <Spinner /> : <Plus className="h-4 w-4" />}
          Создать проект
        </Button>
      </form>
    </Panel>
  );
}

export function SectionHeading({
  numeral,
  title,
  caption,
  right,
}: {
  numeral: string;
  title: string;
  caption?: string;
  right?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-end justify-between gap-4 border-b border-border pb-3">
      <div className="flex items-end gap-3">
        <span className="stage-numeral text-3xl leading-none text-primary/70">{numeral}</span>
        <div>
          <h2 className="font-display text-xl leading-none">{title}</h2>
          {caption ? (
            <p className="mt-1.5 font-mono text-[0.66rem] uppercase tracking-[0.14em] text-muted-foreground">
              {caption}
            </p>
          ) : null}
        </div>
      </div>
      {right}
    </div>
  );
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Неизвестная ошибка";
}

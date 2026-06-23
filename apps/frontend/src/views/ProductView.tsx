import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { AssetsPanel } from "@/components/product/AssetsPanel";
import { ConceptsPanel } from "@/components/product/ConceptsPanel";
import { IdeasPanel } from "@/components/product/IdeasPanel";
import { Panel } from "@/components/ui/panel";
import { ErrorRow, LoadingRow } from "@/components/ui/states";
import { ApiError, getIdeas, getProduct, getProject } from "@/lib/api";
import { describeError } from "@/views/ProjectsView";

export function ProductView({ productId }: { productId: string }) {
  const product = useQuery({
    queryKey: ["product", productId],
    queryFn: () => getProduct(productId),
  });
  const project = useQuery({
    queryKey: ["project", product.data?.project_id],
    queryFn: () => getProject(product.data!.project_id),
    enabled: !!product.data?.project_id,
  });
  const ideas = useQuery({
    queryKey: ["ideas", productId],
    queryFn: () => getIdeas(productId),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
  const hasIdeas = !!ideas.data;

  const crumbs = [
    { label: "проекты", to: { name: "projects" as const } },
    ...(project.data
      ? [{ label: project.data.name, to: { name: "project" as const, id: project.data.id } }]
      : []),
    { label: product.data?.title ?? "товар" },
  ];

  return (
    <AppShell crumbs={crumbs}>
      {product.isLoading ? (
        <LoadingRow label="Загрузка товара…" />
      ) : product.isError ? (
        <ErrorRow message={describeError(product.error)} />
      ) : product.data ? (
        <div className="space-y-8">
          <header className="animate-rise">
            <p className="font-mono text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground">
              Товар
            </p>
            <h1 className="mt-1 font-display text-3xl tracking-tight sm:text-4xl">
              {product.data.title}
            </h1>
          </header>

          <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
            <DataPanel
              advantages={product.data.advantages}
              audience={product.data.target_audience}
              attributes={product.data.attributes_json}
              requirements={product.data.requirements_json}
            />
            <AssetsPanel productId={productId} />
          </div>

          <IdeasPanel productId={productId} />
          <ConceptsPanel productId={productId} hasIdeas={hasIdeas} />
        </div>
      ) : null}
    </AppShell>
  );
}

function DataPanel({
  advantages,
  audience,
  attributes,
  requirements,
}: {
  advantages: string | null;
  audience: string | null;
  attributes: Record<string, unknown>;
  requirements: Record<string, unknown>;
}) {
  const attrs = Object.entries(attributes ?? {});
  const reqs = Object.entries(requirements ?? {});
  return (
    <Panel className="space-y-5 p-5 sm:p-6">
      <h3 className="font-display text-base">Данные товара</h3>

      <DataField label="Преимущества">
        {advantages ? <p className="text-sm leading-relaxed">{advantages}</p> : <Empty />}
      </DataField>

      <DataField label="Целевая аудитория">
        {audience ? <p className="text-sm">{audience}</p> : <Empty />}
      </DataField>

      <DataField label="Характеристики">
        {attrs.length > 0 ? <KvTable rows={attrs} /> : <Empty />}
      </DataField>

      <DataField label="Требования к карточкам">
        {reqs.length > 0 ? <KvTable rows={reqs} /> : <Empty />}
      </DataField>
    </Panel>
  );
}

function DataField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      {children}
    </div>
  );
}

function KvTable({ rows }: { rows: [string, unknown][] }) {
  return (
    <dl className="divide-y divide-border overflow-hidden rounded-md border border-border">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-3 px-3 py-1.5 text-sm">
          <dt className="w-36 shrink-0 font-mono text-[0.78rem] text-muted-foreground">{k}</dt>
          <dd className="flex-1">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Empty() {
  return <p className="text-sm italic text-muted-foreground/60">не заполнено</p>;
}

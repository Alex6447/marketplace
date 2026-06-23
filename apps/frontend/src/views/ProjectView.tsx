import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Box, PackagePlus, Plus } from "lucide-react";
import { useState } from "react";

import { SectionHeading, describeError } from "@/views/ProjectsView";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorRow, LoadingRow, Spinner } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { createProduct, getProject, listProducts, type Product } from "@/lib/api";
import { parseKeyValues } from "@/lib/kv";
import { href, navigate } from "@/lib/router";

export function ProjectView({ projectId }: { projectId: string }) {
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
  });
  const products = useQuery({
    queryKey: ["products", projectId],
    queryFn: () => listProducts(projectId),
  });

  return (
    <AppShell
      crumbs={[
        { label: "проекты", to: { name: "projects" } },
        { label: project.data?.name ?? "проект" },
      ]}
    >
      <div className="space-y-8">
        <header className="animate-rise">
          <p className="font-mono text-[0.66rem] uppercase tracking-[0.16em] text-muted-foreground">
            Проект
          </p>
          <h1 className="mt-1 font-display text-3xl tracking-tight sm:text-4xl">
            {project.data?.name ?? "…"}
          </h1>
          {project.data?.brand_style ? (
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {project.data.brand_style}
            </p>
          ) : null}
        </header>

        <div className="grid gap-8 lg:grid-cols-[1fr_24rem]">
          <section className="order-2 lg:order-1">
            <SectionHeading numeral="02" title="Товары" caption="Карточки генерируются по товару" />
            {products.isLoading ? (
              <LoadingRow />
            ) : products.isError ? (
              <ErrorRow message={describeError(products.error)} />
            ) : products.data && products.data.length > 0 ? (
              <ul className="grid gap-3">
                {products.data.map((p, i) => (
                  <ProductRow key={p.id} product={p} index={i} />
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={Box}
                title="В проекте ещё нет товаров"
                description="Добавьте товар справа: название, характеристики, преимущества и аудиторию — это вход для генерации идей и концепций."
              />
            )}
          </section>

          <aside className="order-1 lg:order-2">
            <CreateProductPanel projectId={projectId} />
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

function ProductRow({ product, index }: { product: Product; index: number }) {
  const attrCount = Object.keys(product.attributes_json ?? {}).length;
  return (
    <li className="animate-rise" style={{ animationDelay: `${index * 50}ms` }}>
      <a
        href={href({ name: "product", id: product.id })}
        onClick={(e) => {
          e.preventDefault();
          navigate({ name: "product", id: product.id });
        }}
        className="group block"
      >
        <Panel className="flex items-center justify-between gap-4 p-4 transition-colors hover:border-primary/50">
          <div className="min-w-0">
            <h3 className="truncate font-display text-base">{product.title}</h3>
            <p className="mt-1 truncate text-sm text-muted-foreground">
              {product.advantages || product.target_audience || "описание не заполнено"}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-4">
            <span className="hidden font-mono text-[0.66rem] uppercase tracking-[0.12em] text-muted-foreground sm:inline">
              {attrCount} хар-к
            </span>
            <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
          </div>
        </Panel>
      </a>
    </li>
  );
}

function CreateProductPanel({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [advantages, setAdvantages] = useState("");
  const [audience, setAudience] = useState("");
  const [attributes, setAttributes] = useState("");
  const [requirements, setRequirements] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      createProduct(projectId, {
        title: title.trim(),
        advantages: advantages.trim() || null,
        target_audience: audience.trim() || null,
        attributes_json: parseKeyValues(attributes),
        requirements_json: parseKeyValues(requirements),
      }),
    onSuccess: (product) => {
      qc.invalidateQueries({ queryKey: ["products", projectId] });
      navigate({ name: "product", id: product.id });
    },
  });

  return (
    <Panel className="sticky top-24 p-5">
      <div className="mb-4 flex items-center gap-2">
        <PackagePlus className="h-4 w-4 text-primary" />
        <h2 className="font-display text-base">Новый товар</h2>
      </div>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) mutation.mutate();
        }}
      >
        <Field label="Название" htmlFor="product-title">
          <Input
            id="product-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Напр. Рюкзак городской 20 л"
            maxLength={512}
            required
          />
        </Field>
        <Field label="Преимущества" hint="свободный текст" htmlFor="product-adv">
          <Textarea
            id="product-adv"
            value={advantages}
            onChange={(e) => setAdvantages(e.target.value)}
            placeholder="Водонепроницаемый, лёгкий, отделение для ноутбука 15”."
          />
        </Field>
        <Field label="Целевая аудитория" hint="необязательно" htmlFor="product-aud">
          <Input
            id="product-aud"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            placeholder="Студенты, городские жители 18–30"
            maxLength={512}
          />
        </Field>
        <Field label="Характеристики" hint="ключ: значение, по строкам" htmlFor="product-attrs">
          <Textarea
            id="product-attrs"
            value={attributes}
            onChange={(e) => setAttributes(e.target.value)}
            placeholder={"Объём: 20 л\nМатериал: нейлон 600D\nЦвет: графит"}
            className="font-mono text-[0.8rem]"
          />
        </Field>
        <Field label="Требования к карточкам" hint="ключ: значение" htmlFor="product-reqs">
          <Textarea
            id="product-reqs"
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            placeholder={"Маркетплейс: Ozon\nФормат: 1080x1440\nКол-во слайдов: 6"}
            className="font-mono text-[0.8rem]"
          />
        </Field>
        {mutation.isError ? <ErrorRow message={describeError(mutation.error)} /> : null}
        <Button type="submit" className="w-full" disabled={!title.trim() || mutation.isPending}>
          {mutation.isPending ? <Spinner /> : <Plus className="h-4 w-4" />}
          Добавить товар
        </Button>
      </form>
    </Panel>
  );
}

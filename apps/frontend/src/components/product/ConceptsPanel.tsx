import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  Frame,
  Layout,
  Lock,
  Palette,
  RefreshCw,
  Shapes,
  Sparkles,
  Type,
} from "lucide-react";
import type { ReactNode } from "react";

import { Badge, RoleTag } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorRow, Spinner } from "@/components/ui/states";
import { StageHeader } from "@/components/product/StageHeader";
import { ApiError, generateCards, getCards, type Card } from "@/lib/api";
import { describeError } from "@/views/ProjectsView";
import { cn } from "@/lib/utils";

export function ConceptsPanel({ productId, hasIdeas }: { productId: string; hasIdeas: boolean }) {
  const qc = useQueryClient();
  const cards = useQuery({
    queryKey: ["cards", productId],
    queryFn: () => getCards(productId),
    enabled: hasIdeas,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  const notGenerated = cards.error instanceof ApiError && cards.error.status === 404;
  const data = cards.data;

  const generate = useMutation({
    mutationFn: (force: boolean) => generateCards(productId, force),
    onSuccess: (res) => qc.setQueryData(["cards", productId], res),
  });

  return (
    <Panel as="section" className="p-5 sm:p-6">
      <StageHeader
        numeral="3"
        title="Визуальные концепции"
        subtitle="Единый контракт LLM ↔ движок текста: композиция, фон, блоки, палитра"
        action={
          data && data.cards.length > 0 ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => generate.mutate(true)}
              disabled={generate.isPending}
            >
              {generate.isPending ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
              Перегенерировать
            </Button>
          ) : null
        }
      />

      {generate.isError ? (
        <div className="mb-4">
          <ErrorRow message={describeError(generate.error)} />
        </div>
      ) : null}

      {!hasIdeas ? (
        <EmptyState
          icon={Lock}
          title="Нужны идеи комплекта"
          description="Концепции опираются на стадию [2]. Сначала сгенерируйте идеи — затем здесь появится сборка концепций."
        />
      ) : cards.isLoading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Spinner /> Загрузка концепций…
        </div>
      ) : data && data.cards.length > 0 ? (
        <div className="space-y-4">
          {data.cards.map((card, i) => (
            <ConceptCard key={card.id} card={card} index={i} />
          ))}
        </div>
      ) : notGenerated || (data && data.cards.length === 0) ? (
        <EmptyState
          icon={Frame}
          title="Концепции ещё не собраны"
          description="Запустите стадию [3] — для каждого слайда из идей система соберёт визуальную концепцию карточки."
          action={
            <Button onClick={() => generate.mutate(false)} disabled={generate.isPending}>
              {generate.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />}
              Сгенерировать концепции
            </Button>
          }
        />
      ) : (
        <ErrorRow message={describeError(cards.error)} />
      )}
    </Panel>
  );
}

function ConceptCard({ card, index }: { card: Card; index: number }) {
  const c = card.concept;
  if (!c) {
    return (
      <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        Концепция для карточки <RoleTag role={card.role} /> ещё пуста.
      </div>
    );
  }
  return (
    <article
      className="animate-rise overflow-hidden rounded-lg border border-border bg-background/40"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <header className="flex items-center gap-3 border-b border-border bg-card/40 px-4 py-3">
        <span className="stage-numeral text-lg text-primary/70">
          {String(card.order + 1).padStart(2, "0")}
        </span>
        <h4 className="flex-1 font-display text-base leading-tight">{c.title}</h4>
        <RoleTag role={c.role} />
      </header>

      <div className="grid gap-4 p-4 sm:grid-cols-2">
        <Spec icon={Layout} label="Композиция">
          {c.composition}
        </Spec>
        <Spec icon={Frame} label="Подача товара">
          {c.product_placement}
        </Spec>
        <Spec icon={Shapes} label="Фон / сцена" className="sm:col-span-2">
          {c.background}
        </Spec>
      </div>

      {c.text_blocks.length > 0 ? (
        <Section icon={Type} label="Текстовые блоки">
          <ul className="grid gap-2">
            {c.text_blocks.map((b, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card/30 px-3 py-2 text-sm"
              >
                <RoleTag role={b.role} />
                <span className="flex-1">{b.text}</span>
                <span className="font-mono text-[0.64rem] uppercase tracking-[0.1em] text-muted-foreground">
                  {b.position}
                  {b.emphasis ? ` · ${b.emphasis}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {c.color_palette.length > 0 ? (
        <Section icon={Palette} label="Палитра">
          <div className="flex flex-wrap gap-2">
            {c.color_palette.map((color, i) => (
              <Swatch key={i} value={color} />
            ))}
          </div>
        </Section>
      ) : null}

      {(c.infographics.length > 0 || c.icons.length > 0) && (
        <div className="grid gap-4 border-t border-border p-4 sm:grid-cols-2">
          {c.infographics.length > 0 ? (
            <ChipList label="Инфографика" items={c.infographics} tone="muted" />
          ) : null}
          {c.icons.length > 0 ? <ChipList label="Иконки" items={c.icons} tone="muted" /> : null}
        </div>
      )}

      {(c.must_have.length > 0 || c.must_not_have.length > 0) && (
        <div className="grid gap-4 border-t border-border p-4 sm:grid-cols-2">
          {c.must_have.length > 0 ? (
            <Constraints
              icon={CheckCircle2}
              label="Должно быть"
              tone="success"
              items={c.must_have}
            />
          ) : null}
          {c.must_not_have.length > 0 ? (
            <Constraints icon={Ban} label="Не должно быть" tone="danger" items={c.must_not_have} />
          ) : null}
        </div>
      )}
    </article>
  );
}

function Spec({
  icon: Icon,
  label,
  children,
  className,
}: {
  icon: typeof Layout;
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="mb-1 flex items-center gap-1.5 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted-foreground">
        <Icon className="h-3 w-3" /> {label}
      </p>
      <p className="text-sm leading-relaxed">{children}</p>
    </div>
  );
}

function Section({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Layout;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-border p-4">
      <p className="mb-2.5 flex items-center gap-1.5 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted-foreground">
        <Icon className="h-3 w-3" /> {label}
      </p>
      {children}
    </div>
  );
}

function ChipList({ label, items, tone }: { label: string; items: string[]; tone: "muted" }) {
  return (
    <div>
      <p className="mb-2 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it, i) => (
          <Badge key={i} tone={tone}>
            {it}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function Constraints({
  icon: Icon,
  label,
  items,
  tone,
}: {
  icon: typeof CheckCircle2;
  label: string;
  items: string[];
  tone: "success" | "danger";
}) {
  return (
    <div>
      <p
        className={cn(
          "mb-2 flex items-center gap-1.5 font-mono text-[0.64rem] uppercase tracking-[0.14em]",
          tone === "success" ? "text-[hsl(var(--success))]" : "text-destructive",
        )}
      >
        <Icon className="h-3 w-3" /> {label}
      </p>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="text-sm text-muted-foreground">
            {it}
          </li>
        ))}
      </ul>
    </div>
  );
}

const HEX = /^#?[0-9a-fA-F]{3,8}$/;

function Swatch({ value }: { value: string }) {
  const isHex = HEX.test(value.trim());
  const css = isHex ? (value.startsWith("#") ? value : `#${value}`) : value;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card/40 py-0.5 pl-1 pr-2.5 text-xs">
      <span
        className="h-4 w-4 rounded-full border border-border"
        style={{ background: css }}
        aria-hidden
      />
      <span className="font-mono text-[0.68rem]">{value}</span>
    </span>
  );
}

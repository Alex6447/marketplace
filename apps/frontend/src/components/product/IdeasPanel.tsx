import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lightbulb, RefreshCw, Sparkles } from "lucide-react";

import { Badge, RoleTag } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorRow, Spinner } from "@/components/ui/states";
import { ApiError, generateIdeas, getIdeas, type IdeaSlide } from "@/lib/api";
import { describeError } from "@/views/ProjectsView";
import { StageHeader } from "@/components/product/StageHeader";

export function IdeasPanel({ productId }: { productId: string }) {
  const qc = useQueryClient();
  const ideas = useQuery({
    queryKey: ["ideas", productId],
    queryFn: () => getIdeas(productId),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  const notGenerated = ideas.error instanceof ApiError && ideas.error.status === 404;
  const data = ideas.data?.ideas;

  const generate = useMutation({
    mutationFn: (force: boolean) => generateIdeas(productId, force),
    onSuccess: (res) => {
      qc.setQueryData(["ideas", productId], res);
      // концепции опираются на идеи — пусть перечитаются при следующем заходе
      qc.invalidateQueries({ queryKey: ["cards", productId] });
    },
  });

  return (
    <Panel as="section" className="p-5 sm:p-6">
      <StageHeader
        numeral="2"
        title="Идеи комплекта"
        subtitle="LLM проектирует слайды: роли, смыслы, акценты, тон"
        action={
          data ? (
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

      {ideas.isLoading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Spinner /> Загрузка идей…
        </div>
      ) : data ? (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Общий тон:</span>
            <Badge tone="primary">{data.overall_tone}</Badge>
            {data.notes ? <span className="text-muted-foreground">· {data.notes}</span> : null}
          </div>
          <ol className="grid gap-3">
            {data.slides.map((slide, i) => (
              <SlideCard key={i} slide={slide} index={i} />
            ))}
          </ol>
        </div>
      ) : notGenerated ? (
        <EmptyState
          icon={Lightbulb}
          title="Идеи ещё не сгенерированы"
          description="Запустите стадию [2] — система предложит структуру комплекта карточек на основе данных товара."
          action={
            <Button onClick={() => generate.mutate(false)} disabled={generate.isPending}>
              {generate.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />}
              Сгенерировать идеи
            </Button>
          }
        />
      ) : (
        <ErrorRow message={describeError(ideas.error)} />
      )}
    </Panel>
  );
}

function SlideCard({ slide, index }: { slide: IdeaSlide; index: number }) {
  return (
    <li
      className="animate-rise rounded-md border border-border bg-background/40 p-4"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <div className="flex items-start gap-3">
        <span className="stage-numeral mt-0.5 text-lg text-muted-foreground/60">
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-display text-[0.98rem] leading-tight">{slide.title}</h4>
            <RoleTag role={slide.role} />
          </div>
          <ul className="mt-2 space-y-1">
            {slide.key_messages.map((m, i) => (
              <li key={i} className="flex gap-2 text-sm text-muted-foreground">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-primary/70" />
                {m}
              </li>
            ))}
          </ul>
          {slide.accents.length > 0 ? (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {slide.accents.map((a, i) => (
                <Badge key={i} tone="muted">
                  {a}
                </Badge>
              ))}
            </div>
          ) : null}
          <p className="mt-2.5 font-mono text-[0.66rem] uppercase tracking-[0.12em] text-muted-foreground/70">
            тон · {slide.tone}
          </p>
        </div>
      </div>
    </li>
  );
}

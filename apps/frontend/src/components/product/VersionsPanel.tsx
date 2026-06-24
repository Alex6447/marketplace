import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  ImageOff,
  Layers,
  Lock,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Type,
  Wand2,
} from "lucide-react";
import { useState } from "react";

import { Badge, RoleTag } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Panel } from "@/components/ui/panel";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, ErrorRow, Spinner } from "@/components/ui/states";
import { StageHeader } from "@/components/product/StageHeader";
import {
  ApiError,
  generateCardImage,
  getCards,
  listCardVersions,
  listFeedback,
  MARKETPLACE_TEMPLATES,
  regenerateFromFeedback,
  renderCardText,
  submitFeedback,
  waitForJob,
  type Card,
  type CardImageMode,
  type CardVersion,
  type Feedback,
  type FeedbackStage,
  type Job,
} from "@/lib/api";
import { describeError } from "@/views/ProjectsView";
import { cn } from "@/lib/utils";

// Стадии, которые перегенерируются автоматически по фидбэку (см. feedback.py).
const AUTO_REGEN_STAGES: ReadonlySet<FeedbackStage> = new Set(["concept", "image", "text"]);

const STAGE_LABELS: Record<FeedbackStage, string> = {
  concept: "концепция [3]",
  image: "изображение [5]",
  text: "текст [6]",
  ideas: "идеи [2]",
  unknown: "не определена",
};

function str(record: Record<string, unknown>, key: string): string | null {
  const v = record[key];
  return typeof v === "string" ? v : null;
}

export function VersionsPanel({
  productId,
  hasConcepts,
}: {
  productId: string;
  hasConcepts: boolean;
}) {
  const cards = useQuery({
    queryKey: ["cards", productId],
    queryFn: () => getCards(productId),
    enabled: hasConcepts,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  const list = cards.data?.cards ?? [];

  return (
    <Panel as="section" className="p-5 sm:p-6">
      <StageHeader
        numeral="5–9"
        title="Студия карточек"
        subtitle="Генерация изображения [5], наложение текста [6] и правки по фидбэку [9] — с историей версий"
      />

      {!hasConcepts ? (
        <EmptyState
          icon={Lock}
          title="Нужны концепции карточек"
          description="Студия опирается на стадию [3]. Сначала соберите концепции — затем здесь можно генерировать изображения и накладывать текст."
        />
      ) : cards.isLoading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Spinner /> Загрузка карточек…
        </div>
      ) : list.length > 0 ? (
        <div className="space-y-5">
          {list.map((card, i) => (
            <CardStudio key={card.id} card={card} index={i} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Layers}
          title="В наборе нет карточек"
          description="Сгенерируйте концепции на стадии [3] — для каждой карточки появится своя студия с версиями."
        />
      )}
    </Panel>
  );
}

function CardStudio({ card, index }: { card: Card; index: number }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<CardImageMode>("edit");
  const [progress, setProgress] = useState<number | null>(null);

  const versions = useQuery({
    queryKey: ["versions", card.id],
    queryFn: () => listCardVersions(card.id),
  });

  const generate = useMutation({
    mutationFn: async () => {
      const job = await generateCardImage(card.id, { mode });
      return waitForJob(job.id, (j: Job) => setProgress(j.progress));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["versions", card.id] }),
    onSettled: () => setProgress(null),
  });

  const data = versions.data ?? [];

  return (
    <article
      className="animate-rise overflow-hidden rounded-lg border border-border bg-background/40"
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-card/40 px-4 py-3">
        <span className="stage-numeral text-lg text-primary/70">
          {String(card.order + 1).padStart(2, "0")}
        </span>
        <h4 className="min-w-0 flex-1 truncate font-display text-base leading-tight">
          {card.concept?.title ?? card.role}
        </h4>
        <RoleTag role={card.role} />
      </header>

      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <ModeToggle mode={mode} onChange={setMode} disabled={generate.isPending} />
        <Button size="sm" onClick={() => generate.mutate()} disabled={generate.isPending}>
          {generate.isPending ? <Spinner /> : <Wand2 className="h-3.5 w-3.5" />}
          {data.length > 0 ? "Новая версия" : "Сгенерировать изображение"}
        </Button>
        {generate.isPending && progress !== null ? (
          <JobProgress value={progress} label="генерация" />
        ) : null}
      </div>

      {generate.isError ? (
        <div className="px-4 pb-3">
          <ErrorRow message={describeError(generate.error)} />
        </div>
      ) : null}

      <div className="border-t border-border p-4">
        {versions.isLoading ? (
          <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Spinner /> Загрузка версий…
          </div>
        ) : versions.isError ? (
          <ErrorRow message={describeError(versions.error)} />
        ) : data.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.map((v) => (
              <VersionCard key={v.id} version={v} cardId={card.id} />
            ))}
          </div>
        ) : (
          <p className="py-4 text-center text-sm italic text-muted-foreground/70">
            Версий пока нет — сгенерируйте изображение, чтобы товар оказался на новой сцене.
          </p>
        )}
      </div>
    </article>
  );
}

function ModeToggle({
  mode,
  onChange,
  disabled,
}: {
  mode: CardImageMode;
  onChange: (m: CardImageMode) => void;
  disabled?: boolean;
}) {
  const opts: { value: CardImageMode; label: string; hint: string }[] = [
    { value: "edit", label: "edit", hint: "editing-модель" },
    { value: "composite", label: "composite", hint: "вырез 1:1" },
  ];
  return (
    <div className="inline-flex rounded-md border border-border p-0.5 text-xs" role="group">
      {opts.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={disabled}
          title={o.hint}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-[5px] px-2.5 py-1 font-mono uppercase tracking-[0.1em] transition-colors disabled:opacity-50",
            mode === o.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function JobProgress({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex min-w-[8rem] flex-1 items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-300"
          style={{ width: `${Math.max(4, value)}%` }}
        />
      </div>
      <span className="font-mono text-[0.62rem] uppercase tracking-[0.1em] text-muted-foreground">
        {label} {value}%
      </span>
    </div>
  );
}

function VersionCard({ version, cardId }: { version: CardVersion; cardId: string }) {
  const hasFinal = !!version.final_url;
  const [view, setView] = useState<"image" | "final">(hasFinal ? "final" : "image");
  const [expanded, setExpanded] = useState(false);

  const src = view === "final" ? version.final_url : version.image_url;
  const mode = str(version.gen_params_json, "mode");
  const cached = version.gen_params_json["cached"] === true;

  return (
    <div className="flex flex-col overflow-hidden rounded-md border border-border bg-card/30">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="font-mono text-xs text-muted-foreground">v{version.version_no}</span>
        {mode ? <RoleTag role={mode} /> : null}
        {hasFinal ? <Badge tone="success">с текстом</Badge> : null}
        {cached ? <Badge tone="muted">кэш</Badge> : null}
      </div>

      <Thumb src={src} alt={`Версия ${version.version_no}`} />

      {hasFinal ? (
        <div className="flex border-b border-border text-xs">
          {(["image", "final"] as const).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={cn(
                "flex-1 py-1.5 font-mono uppercase tracking-[0.1em] transition-colors",
                view === v
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {v === "image" ? "[5] фон" : "[6] текст"}
            </button>
          ))}
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center justify-center gap-1.5 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        {expanded ? "Свернуть" : "Текст и правки"}
      </button>

      {expanded ? (
        <div className="space-y-4 border-t border-border p-3">
          <TextOverlayControls version={version} cardId={cardId} hasFinal={hasFinal} />
          <FeedbackBlock version={version} cardId={cardId} />
        </div>
      ) : null}
    </div>
  );
}

function Thumb({ src, alt }: { src: string | null; alt: string }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="aspect-square bg-background/50">
      {src && !broken ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          onError={() => setBroken(true)}
          className="h-full w-full object-contain"
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-muted-foreground/50">
          <ImageOff className="h-6 w-6" />
        </div>
      )}
    </div>
  );
}

function TextOverlayControls({
  version,
  cardId,
  hasFinal,
}: {
  version: CardVersion;
  cardId: string;
  hasFinal: boolean;
}) {
  const qc = useQueryClient();
  const [template, setTemplate] = useState<string>(MARKETPLACE_TEMPLATES[0].key);
  const [progress, setProgress] = useState<number | null>(null);

  const render = useMutation({
    mutationFn: async () => {
      const job = await renderCardText(version.id, template);
      return waitForJob(job.id, (j: Job) => setProgress(j.progress));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["versions", cardId] }),
    onSettled: () => setProgress(null),
  });

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted-foreground">
        <Type className="h-3 w-3" /> Наложение текста [6]
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          disabled={render.isPending}
          className="h-8 flex-1 rounded-md border border-input bg-background/40 px-2 text-xs focus-visible:border-primary focus-visible:outline-none disabled:opacity-50"
        >
          {MARKETPLACE_TEMPLATES.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          variant="outline"
          onClick={() => render.mutate()}
          disabled={render.isPending}
        >
          {render.isPending ? <Spinner /> : hasFinal ? <RefreshCw className="h-3.5 w-3.5" /> : null}
          {hasFinal ? "Перерендерить" : "Нанести текст"}
        </Button>
      </div>
      {render.isPending && progress !== null ? (
        <JobProgress value={progress} label="рендер" />
      ) : null}
      {render.isError ? <ErrorRow message={describeError(render.error)} /> : null}
    </div>
  );
}

function FeedbackBlock({ version, cardId }: { version: CardVersion; cardId: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");

  const history = useQuery({
    queryKey: ["feedback", version.id],
    queryFn: () => listFeedback(version.id),
  });

  const send = useMutation({
    mutationFn: () => submitFeedback(version.id, text.trim()),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["feedback", version.id] });
    },
  });

  const items = history.data ?? [];

  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 font-mono text-[0.64rem] uppercase tracking-[0.14em] text-muted-foreground">
        <MessageSquare className="h-3 w-3" /> Фидбэк [9]
      </p>

      <Field label="Правка текстом" htmlFor={`fb-${version.id}`}>
        <Textarea
          id={`fb-${version.id}`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Напр.: фон светлее, текст крупнее, добавить акцент на гарантию."
          className="min-h-[64px] text-sm"
          disabled={send.isPending}
        />
      </Field>
      <div className="flex justify-end">
        <Button size="sm" onClick={() => send.mutate()} disabled={!text.trim() || send.isPending}>
          {send.isPending ? <Spinner /> : <Send className="h-3.5 w-3.5" />}
          Разобрать фидбэк
        </Button>
      </div>
      {send.isError ? <ErrorRow message={describeError(send.error)} /> : null}

      {items.length > 0 ? (
        <ul className="space-y-2 pt-1">
          {items.map((fb) => (
            <FeedbackItem key={fb.id} feedback={fb} cardId={cardId} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FeedbackItem({ feedback, cardId }: { feedback: Feedback; cardId: string }) {
  const qc = useQueryClient();
  const [progress, setProgress] = useState<number | null>(null);
  const parsed = feedback.parsed_action;
  const canRegen = !!parsed && AUTO_REGEN_STAGES.has(parsed.target_stage);

  const regen = useMutation({
    mutationFn: async () => {
      const job = await regenerateFromFeedback(feedback.id);
      return waitForJob(job.id, (j: Job) => setProgress(j.progress));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["versions", cardId] }),
    onSettled: () => setProgress(null),
  });

  return (
    <li className="rounded-md border border-border bg-background/40 p-2.5 text-xs">
      <p className="text-foreground">«{feedback.text}»</p>
      {parsed ? (
        <div className="mt-2 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="primary">{STAGE_LABELS[parsed.target_stage]}</Badge>
            <Badge tone="muted">{parsed.action}</Badge>
            <span className="font-mono text-[0.6rem] text-muted-foreground">
              увер. {Math.round(parsed.confidence * 100)}%
            </span>
          </div>
          {parsed.summary ? <p className="text-muted-foreground">{parsed.summary}</p> : null}
          {parsed.changes.length > 0 ? (
            <ul className="space-y-0.5">
              {parsed.changes.map((ch, i) => (
                <li key={i} className="flex gap-1.5 text-muted-foreground">
                  <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-primary/70" />
                  <span>
                    <span className="font-mono">{ch.field}</span>
                    <span className="opacity-70"> · {ch.operation}</span>
                    {ch.instruction ? ` — ${ch.instruction}` : ""}
                    {ch.value != null ? `: ${JSON.stringify(ch.value)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {parsed.notes ? <p className="italic text-muted-foreground/70">{parsed.notes}</p> : null}

          {canRegen ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button
                size="sm"
                variant="outline"
                onClick={() => regen.mutate()}
                disabled={regen.isPending}
              >
                {regen.isPending ? <Spinner /> : <Sparkles className="h-3.5 w-3.5" />}
                Перегенерировать стадию
              </Button>
              {regen.isPending && progress !== null ? (
                <JobProgress value={progress} label="правка" />
              ) : null}
            </div>
          ) : (
            <p className="italic text-muted-foreground/70">
              Стадия требует ручного решения — авто-перегенерация недоступна.
            </p>
          )}
          {regen.isError ? <ErrorRow message={describeError(regen.error)} /> : null}
        </div>
      ) : (
        <p className="mt-1 italic text-muted-foreground/70">Фидбэк не разобран.</p>
      )}
    </li>
  );
}

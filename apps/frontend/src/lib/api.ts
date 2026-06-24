// Тонкий клиент к API. В dev запросы идут на относительные пути и проксируются
// Vite на FastAPI (см. vite.config.ts); в production статику и /api раздаёт nginx.
//
// Типы повторяют DTO бэкенда (apps/api/.../schemas.py) и контракты пайплайна
// (marketplace_shared.pipeline) — единый контракт проекта на стороне фронта.

const API = "/api";

/** Ошибка API с HTTP-статусом — экраны различают 404/409/502 и т.п. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* тело не JSON — оставляем статус */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Типы -------------------------------------------------------------------

export interface HealthResponse {
  status: string;
}

export interface Project {
  id: string;
  name: string;
  brand_style: string | null;
  created_at: string;
}

export interface Product {
  id: string;
  project_id: string;
  title: string;
  attributes_json: Record<string, unknown>;
  advantages: string | null;
  target_audience: string | null;
  requirements_json: Record<string, unknown>;
}

export interface ProductAsset {
  id: string;
  product_id: string;
  type: string;
  s3_key: string;
  mask_s3_key: string | null;
  url: string | null;
}

export interface IdeaSlide {
  role: string;
  title: string;
  key_messages: string[];
  accents: string[];
  tone: string;
}

export interface ProductIdeas {
  slides: IdeaSlide[];
  overall_tone: string;
  notes: string | null;
}

export interface IdeasRead {
  product_id: string;
  ideas: ProductIdeas;
}

export interface TextBlock {
  text: string;
  role: string;
  position: string;
  emphasis: string | null;
}

export interface CardConcept {
  role: string;
  title: string;
  composition: string;
  product_placement: string;
  background: string;
  text_blocks: TextBlock[];
  infographics: string[];
  icons: string[];
  color_palette: string[];
  must_have: string[];
  must_not_have: string[];
}

export interface Card {
  id: string;
  role: string;
  order: number;
  concept: CardConcept | null;
}

export interface CardSet {
  id: string;
  product_id: string;
  status: string;
  cards: Card[];
}

// --- Версии, задачи и фидбэк (стадии [5]/[6]/[9]) ---------------------------

export type JobStatus = "pending" | "running" | "success" | "failure";

/** Фоновая задача генерации (таблица Job) — статус и прогресс стадий [4]/[5]/[6]/[9]. */
export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  progress: number;
  stage: string | null;
  result_json: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
}

export type CardImageMode = "edit" | "composite";

/** Версия карточки: изображение стадии [5] (+ финал с текстом стадии [6]). */
export interface CardVersion {
  id: string;
  card_id: string;
  version_no: number;
  image_s3_key: string | null;
  final_s3_key: string | null;
  gen_params_json: Record<string, unknown>;
  created_at: string;
  image_url: string | null;
  final_url: string | null;
}

export type FeedbackStage = "concept" | "image" | "text" | "ideas" | "unknown";
export type FeedbackAction = "adjust" | "regenerate";
export type ChangeOperation = "set" | "add" | "remove" | "modify";

export interface FeedbackChange {
  field: string;
  operation: ChangeOperation;
  instruction: string | null;
  value: unknown;
}

/** Разбор свободного фидбэка LLM (стадия [9]): действие + стадия + дельты. */
export interface ParsedFeedback {
  summary: string;
  target_stage: FeedbackStage;
  action: FeedbackAction;
  changes: FeedbackChange[];
  confidence: number;
  notes: string | null;
}

export interface Feedback {
  id: string;
  card_version_id: string;
  text: string;
  parsed_action: ParsedFeedback | null;
  created_at: string;
}

/** Шаблоны маркетплейсов (стадия [6]) — должны совпадать с textrender/templates.py. */
export const MARKETPLACE_TEMPLATES: { key: string; label: string }[] = [
  { key: "ozon-main", label: "Ozon · основная (1:1)" },
  { key: "ozon-promo", label: "Ozon · промо (3:4)" },
  { key: "wildberries-main", label: "Wildberries · основная (3:4)" },
  { key: "yandex_market-main", label: "Яндекс Маркет · основная (1:1)" },
];

// --- Запросы ----------------------------------------------------------------

/** Readiness-проба API (`GET /api/health`). */
export const fetchHealth = () => request<HealthResponse>("/health");

export const listProjects = () => request<Project[]>("/projects");

export const getProject = (id: string) => request<Project>(`/projects/${id}`);

export const createProject = (body: { name: string; brand_style?: string | null }) =>
  request<Project>("/projects", { method: "POST", body: JSON.stringify(body) });

export const listProducts = (projectId: string) =>
  request<Product[]>(`/projects/${projectId}/products`);

export const getProduct = (id: string) => request<Product>(`/products/${id}`);

export interface ProductCreateBody {
  title: string;
  attributes_json?: Record<string, unknown>;
  advantages?: string | null;
  target_audience?: string | null;
  requirements_json?: Record<string, unknown>;
}

export const createProduct = (projectId: string, body: ProductCreateBody) =>
  request<Product>(`/projects/${projectId}/products`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listAssets = (productId: string) =>
  request<ProductAsset[]>(`/products/${productId}/assets`);

/** Загрузка файла товара (multipart) — фото или референс. */
export async function uploadAsset(
  productId: string,
  file: File,
  type: "photo" | "reference",
): Promise<ProductAsset> {
  const form = new FormData();
  form.append("file", file);
  form.append("type", type);
  const res = await fetch(`${API}/products/${productId}/assets`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as ProductAsset;
}

export const getIdeas = (productId: string) => request<IdeasRead>(`/products/${productId}/ideas`);

export const generateIdeas = (productId: string, force = false) =>
  request<IdeasRead>(`/products/${productId}/ideas`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });

export const getCards = (productId: string) => request<CardSet>(`/products/${productId}/cards`);

export const generateCards = (productId: string, force = false) =>
  request<CardSet>(`/products/${productId}/cards`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });

// --- Стадия [5]: генерация изображения карточки -----------------------------

export interface CardImageGenerateBody {
  mode?: CardImageMode;
  model?: string | null;
  seed?: number | null;
  size?: string | null;
  use_references?: boolean;
}

/** Поставить генерацию изображения карточки в очередь (стадия [5]) → Job (202). */
export const generateCardImage = (cardId: string, body: CardImageGenerateBody = {}) =>
  request<Job>(`/cards/${cardId}/generate`, { method: "POST", body: JSON.stringify(body) });

export const listCardVersions = (cardId: string) =>
  request<CardVersion[]>(`/cards/${cardId}/versions`);

// --- Стадия [6]: наложение текста -------------------------------------------

/** Поставить наложение текста концепции на версию карточки в очередь (стадия [6]) → Job. */
export const renderCardText = (versionId: string, templateKey?: string | null) =>
  request<Job>(`/card-versions/${versionId}/text`, {
    method: "POST",
    body: JSON.stringify({ template_key: templateKey ?? null }),
  });

// --- Стадия [9]: фидбэк и перегенерация -------------------------------------

/** Принять фидбэк менеджера к версии и разобрать его LLM (стадия [9]). */
export const submitFeedback = (versionId: string, text: string) =>
  request<Feedback>(`/card-versions/${versionId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const listFeedback = (versionId: string) =>
  request<Feedback[]>(`/card-versions/${versionId}/feedback`);

/** Поставить перегенерацию адресуемой фидбэком стадии в очередь (стадия [9]) → Job. */
export const regenerateFromFeedback = (feedbackId: string, templateKey?: string | null) =>
  request<Job>(`/feedback/${feedbackId}/regenerate`, {
    method: "POST",
    body: JSON.stringify({ template_key: templateKey ?? null }),
  });

// --- Задачи -----------------------------------------------------------------

export const getJob = (jobId: string) => request<Job>(`/jobs/${jobId}`);

const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set(["success", "failure"]);

/**
 * Дождаться завершения фоновой задачи, опрашивая `GET /jobs/{id}`.
 *
 * SSE (`/jobs/{id}/events`) хорош для живого прогресса, но fetch без EventSource
 * усложняет код; для UI достаточно короткого опроса. `onProgress` зовётся на
 * каждое чтение. При статусе failure бросает ошибку с текстом из задачи.
 */
export async function waitForJob(
  jobId: string,
  onProgress?: (job: Job) => void,
  { intervalMs = 800, maxAttempts = 300 }: { intervalMs?: number; maxAttempts?: number } = {},
): Promise<Job> {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const job = await getJob(jobId);
    onProgress?.(job);
    if (TERMINAL_STATUSES.has(job.status)) {
      if (job.status === "failure") {
        throw new ApiError(500, job.error || "Задача завершилась ошибкой");
      }
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new ApiError(504, "Задача не завершилась за отведённое время");
}

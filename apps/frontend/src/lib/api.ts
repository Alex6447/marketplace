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

/** The only place that calls fetch: JSON in and out, errors as ApiError with a Chinese `detail`. */
import { t } from "@/i18n";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

let unauthorized: () => void = () => {};

export function setUnauthorizedHandler(handler: () => void): void {
  unauthorized = handler;
}

export function notifyUnauthorized(): void {
  unauthorized();
}

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.append(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

function detailOf(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((entry) => (entry as { msg?: string }).msg ?? String(entry)).join("；");
  }
  return `HTTP ${status}`;
}

export async function request<T = unknown>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", signal: options.signal };
  if (options.form) {
    init.body = options.form;
  } else if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
    init.headers = { "Content-Type": "application/json" };
  }
  let response: Response;
  try {
    response = await fetch(withQuery(path, options.query), init);
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, t("error.network"));
  }
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) {
    if (response.status === 401) unauthorized();
    throw new ApiError(response.status, detailOf(body, response.status));
  }
  return body as T;
}

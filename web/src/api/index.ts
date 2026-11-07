/** Typed functions per API resource; types come from the backend's OpenAPI schema (pnpm gen:api). */
import type { components } from "./schema";
import { request } from "./client";

type S = components["schemas"];
export type Library = S["LibraryOut"];
export type LibraryIn = S["LibraryIn"];
export type LibraryPatch = S["LibraryPatch"];
export type Run = S["RunOut"];
export type Item = S["ItemOut"];
export type ItemDetail = S["ItemDetail"];
export type ItemPage = S["ItemPage"];
export type Job = S["JobOut"];
export type JobRef = S["JobRef"];
export type ReviewGroup = S["ReviewGroup"];
export type Subject = S["SubjectOut"];
export type Server = S["ServerOut"];
export type ServerIn = S["ServerIn"];
export type ServerPatch = S["ServerPatch"];
export type ServerTest = S["ServerTestOut"];
export type AiCall = S["AiCallOut"];
export type UploadResult = S["UploadResult"];
export type Settings = Record<string, unknown>;
export type Dashboard = S["Dashboard"];
export type HistoryGroup = S["HistoryGroup"];
export type HistoryPage = S["HistoryPage"];
export type LogPage = S["LogPage"];

export interface Choices {
  title?: string | null;
  edition?: string | null;
  bgm?: number | null;
  volumes?: Record<string, string>;
  /** Organize under the title without looking for a Bangumi subject. */
  skip_metadata?: boolean;
}

export const auth = {
  status: () => request<S["AuthStatus"]>("GET", "/api/auth/status"),
  setup: (password: string) => request("POST", "/api/auth/setup", { body: { password } }),
  login: (password: string) => request("POST", "/api/auth/login", { body: { password } }),
  logout: () => request("POST", "/api/auth/logout"),
  changePassword: (old: string, next: string) => request("POST", "/api/auth/password", { body: { old, new: next } }),
};

export const dashboard = {
  get: () => request<Dashboard>("GET", "/api/dashboard"),
};

export const desktop = {
  scanPaths: (libraryId: number, paths: string[]) =>
    request<S["ScanPathsOut"]>("POST", `/api/libraries/${libraryId}/scan-paths`, { body: { paths } }),
  originals: () => request<S["OriginalsOut"]>("GET", "/api/desktop/originals"),
  keep: (ids: number[]) => request("POST", "/api/desktop/originals/keep", { body: { ids } }),
};

export const history = {
  groups: (query: { library_id?: number; status?: string; missing_metadata?: boolean; q?: string; limit?: number; offset?: number }) =>
    request<HistoryPage>("GET", "/api/history/groups", { query }),
  items: (libraryId: number, groupKey: string, status?: string) =>
    request<Item[]>("GET", `/api/history/groups/${libraryId}/${groupKey.split("/").map(encodeURIComponent).join("/")}`,
      { query: { status } }),
};

export const logs = {
  read: (query: { after?: number; level?: string; q?: string }) => request<LogPage>("GET", "/api/logs", { query }),
  downloadUrl: "/api/logs/download",
};

export const jobs = {
  get: (id: number) => request<Job>("GET", `/api/jobs/${id}`),
  recent: () => request<Job[]>("GET", "/api/jobs"),
  cancel: (id: number) => request<Job>("POST", `/api/jobs/${id}/cancel`),
};

export const libraries = {
  list: () => request<Library[]>("GET", "/api/libraries"),
  get: (id: number) => request<Library>("GET", `/api/libraries/${id}`),
  create: (body: LibraryIn) => request<Library>("POST", "/api/libraries", { body }),
  update: (id: number, body: LibraryPatch) => request<Library>("PATCH", `/api/libraries/${id}`, { body }),
  scan: (id: number) => request<JobRef>("POST", `/api/libraries/${id}/scan`),
  series: (id: number) => request<string[]>("GET", `/api/libraries/${id}/series`),
  runs: (id: number) => request<Run[]>("GET", `/api/libraries/${id}/runs`),
  summary: (id: number) => request<S["Summary"]>("GET", `/api/libraries/${id}/summary`),
  templatePreview: (id: number, template: string) =>
    request<S["TemplatePreview"]>("POST", `/api/libraries/${id}/template-preview`, { body: { template } }),
  upload: (id: number, file: File, relativePath: string, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("files", file, relativePath);
    return request<UploadResult>("POST", `/api/libraries/${id}/upload`, { form, signal });
  },
};

/** What a person fills in for a book Bangumi does not have; empty strings and lists clear a field. */
export interface MetadataFields {
  localized_series: string;
  writers: string[];
  publisher: string;
  release_date: string;
  genres: string[];
  summary: string;
}

export interface ItemQuery {
  library_id?: number;
  status?: string;
  review_reason?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export const items = {
  page: (query: ItemQuery) => request<ItemPage>("GET", "/api/items", { query: { ...query } }),
  get: (id: number) => request<ItemDetail>("GET", `/api/items/${id}`),
  execute: (itemIds: number[]) => request<JobRef>("POST", "/api/items/execute", { body: { item_ids: itemIds } }),
  retry: (itemIds: number[]) => request<JobRef>("POST", "/api/items/retry", { body: { item_ids: itemIds } }),
  reorganize: (itemIds: number[], choices: Choices) =>
    request<JobRef>("POST", "/api/items/reorganize", { body: { item_ids: itemIds, ...choices } }),
  editMetadata: (itemIds: number[], choice: { bgm: number } | { fields: MetadataFields }) =>
    request<JobRef>("POST", "/api/items/metadata", { body: { item_ids: itemIds, ...choice } }),
  coverOptions: (itemId: number) => request<S["CoverOptionsOut"]>("GET", `/api/items/${itemId}/cover-options`),
  coverUrl: (itemId: number, width: number, stamp: string | number, page?: string) =>
    `/api/items/${itemId}/cover-image?w=${width}&v=${encodeURIComponent(String(stamp))}${page ? `&page=${encodeURIComponent(page)}` : ""}`,
  chooseCover: (itemId: number, choice: { page: string; left?: number; right?: number }) =>
    request<JobRef>("POST", `/api/items/${itemId}/cover`, { body: choice }),
  cropJackets: (itemIds: number[]) => request<JobRef>("POST", "/api/items/crop-jackets", { body: { item_ids: itemIds } }),
  refreshMetadata: (target: { item_ids: number[] } | { library_id: number }) =>
    request<JobRef>("POST", "/api/items/refresh-metadata", { body: target }),
  cancel: (itemIds: number[]) =>
    request<S["CancelResult"]>("POST", "/api/items/cancel", { body: { item_ids: itemIds } }),
};

export const review = {
  groups: (libraryId?: number) => request<ReviewGroup[]>("GET", "/api/review/groups", { query: { library_id: libraryId } }),
  confirm: (itemIds: number[], choices: Choices) =>
    request<JobRef>("POST", "/api/review/confirm", { body: { item_ids: itemIds, ...choices } }),
  reidentify: (target: { item_ids: number[] } | { library_id: number }) =>
    request<JobRef>("POST", "/api/review/reidentify", { body: target }),
};

export const metadata = {
  search: (q: string, kind: "manga" | "novel") => request<Subject[]>("GET", "/api/metadata/search", { query: { q, kind } }),
  subject: (id: number) => request<Subject>("GET", `/api/metadata/subjects/${id}`),
};

export const settings = {
  get: () => request<Settings>("GET", "/api/settings"),
  update: (changes: Settings) => request<Settings>("PATCH", "/api/settings", { body: changes }),
  testAi: () => request<S["AiTestResult"]>("POST", "/api/settings/ai-test"),
  testProxy: (proxy?: string) => request<S["ProxyTestResult"]>("POST", "/api/settings/proxy-test", { body: { proxy } }),
};

export const servers = {
  list: () => request<Server[]>("GET", "/api/servers"),
  create: (body: ServerIn) => request<Server>("POST", "/api/servers", { body }),
  update: (id: number, body: ServerPatch) => request<Server>("PATCH", `/api/servers/${id}`, { body }),
  remove: (id: number) => request("DELETE", `/api/servers/${id}`),
  test: (id: number) => request<ServerTest>("POST", `/api/servers/${id}/test`),
};

export const aiCalls = {
  recent: (limit = 20) => request<AiCall[]>("GET", "/api/ai/calls", { query: { limit } }),
};

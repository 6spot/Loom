// Chronicle public HTTP API client (C1-T9).
//
// Frontend authority stays downstream of HTTP APIs: this module only calls
// the Rust chronicle-server public boundary (`/api/v1/public/*`, served from
// the proven C0 read model). It never touches application persistence or catalog files.

export interface SearchQuery {
  q: string;
  kind?: string;
  limit?: number;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function searchPath(query: SearchQuery): string {
  const params = new URLSearchParams();
  params.set("q", query.q.trim());
  if (query.kind) params.set("kind", query.kind);
  params.set("limit", String(query.limit ?? 20));
  return `/api/v1/public/search?${params.toString()}`;
}

/** Optional `catalog` snapshot pins the entity detail to the fixed source snapshot. */
export function entityPath(id: string, catalog?: string | null): string {
  const base = `/api/v1/public/entities/${encodeURIComponent(id)}`;
  return catalog ? `${base}?catalog=${encodeURIComponent(catalog)}` : base;
}

export function searchPathFromSearch(search: string): string {
  const incoming = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  return searchPath({
    q: incoming.get("q") ?? "",
    kind: incoming.get("kind") ?? undefined,
    limit: incoming.get("limit") ? Number(incoming.get("limit")) : 20,
  });
}

export async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
    ...init,
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(response.status, "invalid_response", `Chronicle API returned HTTP ${response.status}`);
  }
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string } })?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "request_failed",
      error?.message ?? `Chronicle API returned HTTP ${response.status}`,
    );
  }
  return payload as T;
}

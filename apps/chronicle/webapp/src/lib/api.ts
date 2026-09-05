// Chronicle public HTTP API client (C1-T9).
//
// Frontend authority stays downstream of HTTP APIs: this module only calls
// the Rust chronicle-server public boundary (`/api/v1/public/*`, served from
// the proven C0 read model). It never touches application persistence or catalog files.

export interface TimelineQuery {
  from_year?: number;
  to_year?: number;
  limit?: number;
  offset?: number;
}

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

export function timelinePath(query: TimelineQuery = {}): string {
  const params = new URLSearchParams();
  if (query.from_year !== undefined) params.set("from_year", String(query.from_year));
  if (query.to_year !== undefined) params.set("to_year", String(query.to_year));
  params.set("limit", String(query.limit ?? 50));
  params.set("offset", String(query.offset ?? 0));
  return `/api/v1/public/timeline?${params.toString()}`;
}

export function searchPath(query: SearchQuery): string {
  const params = new URLSearchParams();
  params.set("q", query.q.trim());
  if (query.kind) params.set("kind", query.kind);
  params.set("limit", String(query.limit ?? 20));
  return `/api/v1/public/search?${params.toString()}`;
}

export function eventPath(id: string): string {
  return `/api/v1/public/events/${encodeURIComponent(id)}`;
}

export function entityPath(id: string): string {
  return `/api/v1/public/entities/${encodeURIComponent(id)}`;
}

export function timelinePathFromSearch(search: string): string {
  const incoming = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const query: TimelineQuery = {};
  const fromYear = incoming.get("from_year");
  const toYear = incoming.get("to_year");
  const contextYear = incoming.get("year");
  const limit = incoming.get("limit");
  const offset = incoming.get("offset");
  if (fromYear !== null && fromYear !== "") query.from_year = Number(fromYear);
  if (toYear !== null && toYear !== "") query.to_year = Number(toYear);
  if (query.from_year === undefined && query.to_year === undefined && contextYear !== null && contextYear !== "") {
    query.from_year = Number(contextYear);
    query.to_year = Number(contextYear);
  }
  if (limit !== null && limit !== "") query.limit = Number(limit);
  if (offset !== null && offset !== "") query.offset = Number(offset);
  return timelinePath(query);
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

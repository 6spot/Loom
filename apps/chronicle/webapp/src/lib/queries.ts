import { useQuery } from "@tanstack/react-query";
import { ApiError, entityPath, fetchJSON, searchPathFromSearch } from "./api";
import type { EntityDetail, SearchResponse } from "./types";

/**
 * Composite-history phase locator (C2-R3-T13). The main reading locator is
 * `{version, paragraph_id, phase_id}`; the snapshot (version) is part of the
 * query key so two publications can never share a cached phase context. The
 * source reading locator stays `{stream_id, catalog_sha, unit_id}` and is keyed
 * by `personStateKeys` (T10) instead of being mixed in here.
 */
export interface HistoryPhaseLocator {
  readonly version: string;
  readonly paragraph_id: string;
  readonly phase_id: string | null;
}

export function personStatePhaseKey(locator: HistoryPhaseLocator) {
  return [
    "chronicle",
    "person-state",
    "phase",
    locator.version,
    locator.paragraph_id,
    locator.phase_id ?? null,
  ] as const;
}

export function useEntity(id: string | undefined, catalog?: string | null) {
  return useQuery<EntityDetail, ApiError>({
    queryKey: ["entity", id, catalog ?? null],
    queryFn: () => fetchJSON<EntityDetail>(entityPath(id ?? "", catalog)),
    enabled: !!id,
  });
}

export function useSearch(search: string) {
  const path = searchPathFromSearch(search);
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const q = (params.get("q") ?? "").trim();
  return useQuery<SearchResponse, ApiError>({
    queryKey: ["search", path],
    queryFn: () => fetchJSON<SearchResponse>(path),
    enabled: q.length > 0,
  });
}

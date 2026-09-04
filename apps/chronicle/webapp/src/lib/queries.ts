import { useQuery } from "@tanstack/react-query";
import { ApiError, entityPath, eventPath, fetchJSON, searchPathFromSearch, timelinePathFromSearch } from "./api";
import type { EntityDetail, EventDetail, SearchResponse, TimelineResponse } from "./types";

export function useTimeline(search: string) {
  const path = timelinePathFromSearch(search);
  return useQuery<TimelineResponse, ApiError>({
    queryKey: ["timeline", path],
    queryFn: () => fetchJSON<TimelineResponse>(path),
  });
}

export function useEvent(id: string | undefined) {
  return useQuery<EventDetail, ApiError>({
    queryKey: ["event", id],
    queryFn: () => fetchJSON<EventDetail>(eventPath(id ?? "")),
    enabled: !!id,
  });
}

export function useEntity(id: string | undefined) {
  return useQuery<EntityDetail, ApiError>({
    queryKey: ["entity", id],
    queryFn: () => fetchJSON<EntityDetail>(entityPath(id ?? "")),
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

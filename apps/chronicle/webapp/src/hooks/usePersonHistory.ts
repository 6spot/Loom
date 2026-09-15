import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { isHistoryLocator } from "../lib/history-api";
import {
  isNotFound,
  loadPersonHistoryMetadata,
  loadPersonHistoryPage,
  mappingPhaseIds,
  metadataMapping,
  type MainHistoryLocator,
  type PersonHistoryMapping,
  type PersonHistoryMetadataResponse,
  type PersonHistoryParagraph,
  type PersonHistoryPageResponse,
  type PersonHistoryPublication,
} from "../lib/person-history-api";

export interface PersonHistoryMainLocator {
  readonly version: string | null;
  readonly paragraphId: string | null;
  readonly phaseId: string | null;
}

function asMainLocator(locator: PersonHistoryMainLocator): MainHistoryLocator | null {
  if (locator.version === null || locator.paragraphId === null) return null;
  if (!isHistoryLocator({ version: locator.version, paragraph_id: locator.paragraphId })) return null;
  return {
    version: locator.version,
    paragraphId: locator.paragraphId,
    phaseId: locator.phaseId,
  };
}

function flattenPages(pages: readonly PersonHistoryPageResponse[] | undefined): readonly PersonHistoryParagraph[] {
  const seen = new Set<string>();
  const result: PersonHistoryParagraph[] = [];
  for (const page of pages ?? []) {
    for (const paragraph of page.paragraphs) {
      if (seen.has(paragraph.id)) continue;
      seen.add(paragraph.id);
      result.push(paragraph);
    }
  }
  return result.sort((left, right) => left.ordinal - right.ordinal);
}

export interface PersonHistoryResult {
  readonly metadata: ReturnType<typeof useQuery<PersonHistoryMetadataResponse>>;
  readonly mapping: ReturnType<typeof useQuery<PersonHistoryMetadataResponse>>;
  readonly pages: ReturnType<typeof useInfiniteQuery<PersonHistoryPageResponse>>;
  readonly publication: PersonHistoryPublication | null;
  readonly personVersion: string | null;
  readonly paragraphs: readonly PersonHistoryParagraph[];
  readonly mainMapping: PersonHistoryMapping | null;
  readonly mappingStatus: PersonHistoryMapping["status"] | null;
  readonly mappedPhaseIds: readonly string[];
  readonly mainLocator: MainHistoryLocator | null;
  readonly hasMainLocator: boolean;
  readonly invalidMainLocator: boolean;
  readonly mappingUnavailable: boolean;
  readonly isEmpty: boolean;
  readonly loadMore: () => Promise<unknown>;
}

/**
 * T13's independent person-history reads. The person version is part of every
 * prose/evidence query key, and the optional main-history locator is only used
 * by the separate mapping request. It is never used as a biography fallback.
 */
export function usePersonHistory(
  personId: string,
  requestedPersonVersion: string | null,
  mainLocator: PersonHistoryMainLocator,
): PersonHistoryResult {
  const main = asMainLocator(mainLocator);
  const hasMainLocator = mainLocator.version !== null || mainLocator.paragraphId !== null;
  const invalidMainLocator = hasMainLocator && main === null;
  const metadata = useQuery<PersonHistoryMetadataResponse>({
    queryKey: ["chronicle", "person-history", "metadata", personId, requestedPersonVersion ?? "latest"],
    queryFn: ({ signal }) => loadPersonHistoryMetadata(personId, { personVersion: requestedPersonVersion }, signal),
    enabled: Boolean(personId),
    staleTime: Infinity,
    retry: 1,
  });
  const publication = metadata.data?.publication ?? null;
  const personVersion = publication?.person_history_version ?? null;
  const mapping = useQuery<PersonHistoryMetadataResponse>({
    queryKey: [
      "chronicle",
      "person-history",
      "mapping",
      personId,
      personVersion,
      main?.version ?? null,
      main?.paragraphId ?? null,
      main?.phaseId ?? null,
    ],
    queryFn: ({ signal }) => loadPersonHistoryMetadata(personId, { personVersion, mainHistory: main }, signal),
    enabled: Boolean(publication && personVersion && main),
    staleTime: Infinity,
    retry: 1,
  });
  const pages = useInfiniteQuery<PersonHistoryPageResponse>({
    queryKey: ["chronicle", "person-history", "paragraphs", personId, personVersion],
    queryFn: ({ pageParam, signal }) => loadPersonHistoryPage(personId, personVersion!, {
      start: typeof pageParam === "number" ? pageParam : 0,
      limit: 50,
      signal,
    }),
    initialPageParam: 0,
    getNextPageParam: (page) => page.next_start ?? undefined,
    enabled: Boolean(publication && personVersion),
    staleTime: Infinity,
    retry: 1,
  });
  const mainMapping = metadataMapping(mapping.data);
  const mappedPhaseIds = mappingPhaseIds(mainMapping);
  const paragraphs = useMemo(() => flattenPages(pages.data?.pages), [pages.data?.pages]);
  return {
    metadata,
    mapping,
    pages,
    publication,
    personVersion,
    paragraphs,
    mainMapping,
    mappingStatus: mainMapping?.status ?? null,
    mappedPhaseIds,
    mainLocator: main,
    hasMainLocator,
    invalidMainLocator,
    mappingUnavailable: Boolean(main && mapping.isError && isNotFound(mapping.error)),
    isEmpty: metadata.data?.status === "empty" || metadata.data?.empty === true,
    loadMore: () => pages.fetchNextPage(),
  };
}

// Shared public formatting and URL builders. Browser route ownership stays in App.tsx.

export function formatYear(year: number | null | undefined): string {
  if (year === null || year === undefined || Number.isNaN(Number(year))) return "年代未定";
  const value = Number(year);
  return value < 0 ? `公元前 ${Math.abs(value)} 年` : `公元 ${value} 年`;
}

export function formatTime(time: { start_year?: number | null; end_year?: number | null } = {}): string {
  const start = time.start_year;
  const end = time.end_year;
  if (start === null || start === undefined || end === null || end === undefined) return "年代未定";
  if (start === end) return formatYear(start);
  return `${formatYear(start)} — ${formatYear(end)}`;
}

export function isStudioPath(pathname: string): boolean {
  return pathname === "/studio" || pathname.startsWith("/studio/");
}

/// Public reader hrefs (C2-R1-T17). Chapter identity is always the immutable
/// publication_id; unknown or unpublished versions resolve to a 404 view.
export function chaptersPath(): string {
  return "/chapters";
}

export function chapterPath(publicationId: string): string {
  return `/chapters/${encodeURIComponent(publicationId)}`;
}

/// Continuous reading entries (C2-R2-T15). `/read` is the directory; the
/// per-stream page always pins the exploration snapshot via `catalog` and
/// optionally points at one immutable unit via `at`.
export function readPath(): string {
  return "/read";
}

export function readingPath(
  streamId: string,
  catalogSha?: string | null,
  unitId?: string | null,
): string {
  const path = `${readPath()}/${encodeURIComponent(streamId)}`;
  const params = new URLSearchParams();
  if (catalogSha) params.set("catalog", catalogSha);
  if (unitId) params.set("at", unitId);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

/**
 * Carry only an already-published navigation context to another public page.
 *
 * Search terms and historical-time guesses are deliberately excluded. The
 * fields below are either an immutable published version/paragraph mapping or
 * an opaque, same-origin reading return token created by the application.
 * Existing target parameters win so a destination can intentionally replace a
 * context instead of silently inheriting the caller's position.
 */
const PUBLISHED_CONTEXT_KEYS = [
  "catalog",
  "version",
  "para",
  "phase",
  "person_version",
  "person_history_version",
  "history_version",
  "return",
] as const;

export function withPublishedContext(path: string, currentSearch: string): string {
  const hashIndex = path.indexOf("#");
  const hash = hashIndex >= 0 ? path.slice(hashIndex) : "";
  const withoutHash = hashIndex >= 0 ? path.slice(0, hashIndex) : path;
  const queryIndex = withoutHash.indexOf("?");
  const pathname = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  const target = new URLSearchParams(queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : "");
  const incoming = new URLSearchParams(
    currentSearch.startsWith("?") ? currentSearch.slice(1) : currentSearch,
  );
  for (const key of PUBLISHED_CONTEXT_KEYS) {
    if (!target.has(key)) {
      const value = incoming.get(key);
      if (value !== null && value !== "") target.set(key, value);
    }
  }
  const serialized = target.toString();
  return `${pathname}${serialized ? `?${serialized}` : ""}${hash}`;
}

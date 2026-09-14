// Shared public time formatting and URL builders. Browser route ownership stays in App.tsx.

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

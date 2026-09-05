export type HistoricalTimeSelection =
  | { kind: "year"; year: number }
  | { kind: "period"; fromYear: number; toYear: number };

export const DEFAULT_WORLD_YEAR = 208;
export const MAX_HISTORICAL_PERIOD_YEARS = 100;

function integerValue(value: string | null): number | null {
  if (value === null || !/^-?\d+$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export function isSupportedHistoricalYear(value: number): boolean {
  return Number.isInteger(value) && value >= -10000 && value <= 10000;
}

export function parseHistoricalTime(search: string): HistoricalTimeSelection | null {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const year = integerValue(params.get("year"));
  if (year !== null && isSupportedHistoricalYear(year)) return { kind: "year", year };

  const fromYear = integerValue(params.get("from_year"));
  const toYear = integerValue(params.get("to_year"));
  if (
    fromYear !== null &&
    toYear !== null &&
    isSupportedHistoricalYear(fromYear) &&
    isSupportedHistoricalYear(toYear) &&
    fromYear <= toYear &&
    toYear - fromYear + 1 <= MAX_HISTORICAL_PERIOD_YEARS
  ) {
    if (fromYear === toYear) return { kind: "year", year: fromYear };
    return { kind: "period", fromYear, toYear };
  }
  return null;
}

export function historicalTimeParams(selection: HistoricalTimeSelection): URLSearchParams {
  const params = new URLSearchParams();
  if (selection.kind === "year") {
    params.set("year", String(selection.year));
  } else {
    params.set("from_year", String(selection.fromYear));
    params.set("to_year", String(selection.toYear));
  }
  return params;
}

export function historicalTimeLabel(selection: HistoricalTimeSelection): string {
  const label = (year: number) => (year < 0 ? `公元前 ${Math.abs(year)} 年` : `公元 ${year} 年`);
  return selection.kind === "year"
    ? label(selection.year)
    : `${label(selection.fromYear)} — ${label(selection.toYear)}`;
}

export function worldPathForSelection(selection: HistoricalTimeSelection): string {
  return `/world?${historicalTimeParams(selection).toString()}`;
}

export function worldPathFromSearch(search: string): string {
  return worldPathForSelection(parseHistoricalTime(search) ?? { kind: "year", year: DEFAULT_WORLD_YEAR });
}

export function withHistoricalTime(path: string, currentSearch: string): string {
  const selection = parseHistoricalTime(currentSearch);
  if (!selection) return path;

  const hashIndex = path.indexOf("#");
  const hash = hashIndex >= 0 ? path.slice(hashIndex) : "";
  const withoutHash = hashIndex >= 0 ? path.slice(0, hashIndex) : path;
  const queryIndex = withoutHash.indexOf("?");
  const pathname = queryIndex >= 0 ? withoutHash.slice(0, queryIndex) : withoutHash;
  const query = queryIndex >= 0 ? withoutHash.slice(queryIndex + 1) : "";
  const params = new URLSearchParams(query);
  params.delete("year");
  params.delete("from_year");
  params.delete("to_year");
  for (const [key, value] of historicalTimeParams(selection)) params.set(key, value);
  const serialized = params.toString();
  return `${pathname}${serialized ? `?${serialized}` : ""}${hash}`;
}

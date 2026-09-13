import { fetchJSON } from "./api";
import type { ReadingLocator, NarrativeTime, ContextEntityView } from "./reading-types";
import type { ReadingUrlStrategy } from "../hooks/useReadingPosition";
import type { ReadingStateFact } from "../components/reading/ReadingContextPanel";

export interface HistoryLocator { version: string; paragraph_id: string }
export interface HistorySegment {
  text: string; conclusion_ids: string[]; certainty: "clear" | "uncertain";
  event_id: string | null; event_relation: "current" | "retrospective" | "foreshadow" | "background" | null;
  event_text: string | null;
}
export interface HistoryEntity {
  id: string; name: string; kind: ContextEntityView["kind"];
  importance: "primary" | "other"; states: ReadingStateFact[];
}
export interface HistoryParagraph {
  id: string; ordinal: number; phase_id: string; group_id: string;
  segments: HistorySegment[]; entities: HistoryEntity[];
}
export interface HistoryGroup {
  id: string; year: number | null; period: string | null; label: string;
  first_paragraph_id: string; count: number;
}
export interface HistoryEntry {
  label: string; kind: "event" | "period"; paragraph_id: string; event_id: string | null;
  ordinal: number; year: number | null; period: string | null; excerpt: string;
}
export interface HistoryNavigationSection {
  id: string; label: string; period: string | null; start: number; end: number;
  items: Array<{ paragraph_id: string; ordinal: number; label: string;
    period: string | null; importance: "major" | "detail" }>;
}
export interface HistoryPublication {
  version: string; catalog_sha: string; title: string; paragraph_count: number;
  first_paragraph_id: string; groups: HistoryGroup[]; entry_points: HistoryEntry[];
  navigation: HistoryNavigationSection[];
}
export interface HistoryPage {
  publication_version: string; paragraphs: HistoryParagraph[]; start: number; total: number;
  previous_start: number | null; next_start: number | null;
}
export interface HistoryEvidence {
  id: string; relation: "support" | "supplement" | "contradict" | "background" | "incomparable";
  attribution: string; note: string; quote: string; anchor_id: string;
  publication_id: string; source_id: string; source_title: string;
}
export interface HistoryConclusion {
  id: string; question: string; text: string; certainty: "clear" | "uncertain"; reason: string;
  evidence: HistoryEvidence[];
}
export interface HistorySourceRelation { left: string; right: string; relation: string; reason: string }

const SHA = /^[0-9a-f]{64}$/;
const PARAGRAPH = /^hp_[0-9a-f]{24}$/;
export function isHistoryLocator(value: unknown): value is HistoryLocator {
  if (!value || typeof value !== "object") return false;
  const locator = value as HistoryLocator;
  return typeof locator.version === "string" && SHA.test(locator.version) &&
    typeof locator.paragraph_id === "string" && PARAGRAPH.test(locator.paragraph_id);
}
export function historyPath(locator: HistoryLocator): string {
  if (!isHistoryLocator(locator)) throw new Error("历史阅读位置无效");
  return `/history/${locator.version}/${locator.paragraph_id}`;
}

// Only the shared viewport controller uses these opaque keys. No source stream,
// ReadingUnit or source catalog is created: the public history locator is separate.
const HISTORY_SCOPE = "historical-narrative";
export function historyPositionKey(locator: HistoryLocator): ReadingLocator {
  if (!isHistoryLocator(locator)) throw new Error("历史阅读位置无效");
  return { stream_id: HISTORY_SCOPE, catalog_sha: locator.version, unit_id: locator.paragraph_id };
}
function validPosition(value: unknown): value is ReadingLocator {
  if (!value || typeof value !== "object") return false;
  const key = value as ReadingLocator;
  return key.stream_id === HISTORY_SCOPE && isHistoryLocator({ version: key.catalog_sha, paragraph_id: key.unit_id });
}
export const HISTORY_POSITION_STRATEGY: ReadingUrlStrategy = {
  validate: validPosition,
  storagePrefix: "chronicle.history.v1.",
  build: (key) => {
    if (!validPosition(key)) throw new Error("历史位置范围无效");
    return historyPath({ version: key.catalog_sha, paragraph_id: key.unit_id });
  },
  parse: (raw) => {
    const fail = (detail: string) => ({ ok: false as const, issue: { code: "unsupported_target" as const, detail } });
    let url: URL;
    try { url = new URL(raw, "https://loom.local"); } catch { return fail("历史阅读地址无效。"); }
    if (url.origin !== "https://loom.local") return fail("只支持本站历史阅读地址。");
    const path = /^\/history\/([0-9a-f]{64})(?:\/(hp_[0-9a-f]{24}))?\/?$/.exec(url.pathname);
    if (path) {
      if (url.search) return fail("历史阅读位置已在路径中，请勿附加参数。");
      return { ok: true, location: { stream_id: HISTORY_SCOPE, catalog_sha: path[1], unit_id: path[2] ?? null } };
    }
    if (url.pathname !== "/history" && url.pathname !== "/history/") return fail("历史阅读路径无效。");
    const keys = [...url.searchParams.keys()];
    if (new Set(keys).size !== keys.length || keys.some((key) => !["version", "at"].includes(key))) return fail("历史阅读地址参数无效。");
    const version = url.searchParams.get("version");
    const at = url.searchParams.get("at");
    if (!version || !SHA.test(version) || (at !== null && !PARAGRAPH.test(at))) return fail("历史版本或段落位置无效。");
    return { ok: true, location: { stream_id: HISTORY_SCOPE, catalog_sha: version, unit_id: at } };
  },
};

export function historyTime(group?: HistoryGroup): NarrativeTime {
  const year = group?.year;
  return { mode: "events", status: year == null ? "unknown" : "resolved", event_refs: [],
    from_block_id: null, observations: [], year_key: String(year ?? "unknown"), period_key: group?.period ?? "unknown",
    year_label: year == null ? null : `${year < 0 ? `公元前 ${-year}` : year} 年`,
    period_label: group?.period ?? group?.label ?? "年代未详", precision: year == null ? "unknown" : "year", continues_previous: false };
}
export function historyTimeLabel(group: Pick<HistoryGroup, "year" | "period"> | null | undefined): string {
  if (!group) return "";
  return [group.year == null ? "年代未详" : `${group.year < 0 ? `公元前 ${-group.year}` : group.year} 年`, group.period].filter(Boolean).join(" · ");
}

const API = "/api/v1/public/history";
function validNavigation(pub: HistoryPublication): boolean {
  if (!Array.isArray(pub.navigation) || !pub.navigation.length || pub.navigation.length > pub.paragraph_count) return false;
  if (pub.navigation[0]?.id !== pub.first_paragraph_id) return false;
  const ids = new Set<string>();
  const sections = new Set<string>();
  let cursor = 0;
  for (const section of pub.navigation) {
    if (!section || !PARAGRAPH.test(section.id) || sections.has(section.id) || typeof section.label !== "string" || !section.label.trim()
      || (section.period !== null && typeof section.period !== "string") || section.start !== cursor
      || !Number.isInteger(section.end) || section.end < cursor || section.end >= pub.paragraph_count
      || !Array.isArray(section.items) || !section.items.length || section.items.length > section.end - section.start + 1) return false;
    sections.add(section.id);
    let previous = section.start - 1;
    for (const item of section.items) {
      if (!item || !PARAGRAPH.test(item.paragraph_id) || ids.has(item.paragraph_id)
        || !Number.isInteger(item.ordinal) || item.ordinal <= previous || item.ordinal > section.end
        || typeof item.label !== "string" || !item.label.trim()
        || (item.period !== null && typeof item.period !== "string")
        || !["major", "detail"].includes(item.importance)) return false;
      ids.add(item.paragraph_id); previous = item.ordinal;
    }
    cursor = section.end + 1;
  }
  return cursor === pub.paragraph_count && pub.entry_points.every((entry) => entry && ids.has(entry.paragraph_id));
}
export async function loadHistory(version?: string | null): Promise<HistoryPublication | null> {
  const response = await fetchJSON<{ publication: HistoryPublication | null }>(version === undefined || version === null ? API : `${API}?version=${encodeURIComponent(version)}`);
  const pub = response.publication;
  if (pub && (!SHA.test(pub.version) || (version != null && pub.version !== version) || !PARAGRAPH.test(pub.first_paragraph_id)
    || !Number.isInteger(pub.paragraph_count) || pub.paragraph_count < 1 || pub.paragraph_count > 256
    || !Array.isArray(pub.entry_points) || pub.entry_points.length > 12 || !validNavigation(pub))) throw new Error("历史版本或时间轴数据不完整，请刷新后重试。");
  return pub;
}
export async function loadHistoryPage(version: string, query: { at?: string; start?: number }, signal?: AbortSignal): Promise<HistoryPage> {
  const params = new URLSearchParams({ version, limit: "20" });
  if (query.at !== undefined) params.set("at", query.at);
  if (query.start !== undefined) params.set("start", String(query.start));
  const page = await fetchJSON<HistoryPage>(`${API}/paragraphs?${params}`, { signal });
  if (page.publication_version !== version || page.total > 256 || page.paragraphs.length > 50 || !page.paragraphs.every((p, n) => PARAGRAPH.test(p.id) && p.ordinal === page.start + n)) throw new Error("正文与当前历史版本不一致。");
  return page;
}
export async function loadHistoryConclusion(version: string, id: string) {
  const result = await fetchJSON<{ publication_version: string; conclusion: HistoryConclusion; source_relations: HistorySourceRelation[] }>(`${API}/conclusions/${encodeURIComponent(id)}?version=${encodeURIComponent(version)}`);
  if (result.publication_version !== version || result.conclusion.id !== id) throw new Error("原文依据与当前版本不一致。");
  return result;
}

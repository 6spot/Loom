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
export interface HistoryPublication {
  version: string; catalog_sha: string; title: string; paragraph_count: number;
  first_paragraph_id: string; groups: HistoryGroup[]; entry_points: HistoryEntry[];
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
  return `/history?${new URLSearchParams({ version: locator.version, at: locator.paragraph_id })}`;
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
    if (url.origin !== "https://loom.local" || url.pathname !== "/history") return fail("只支持本站历史阅读地址。");
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
export async function loadHistory(version?: string | null): Promise<HistoryPublication | null> {
  const response = await fetchJSON<{ publication: HistoryPublication | null }>(version === undefined || version === null ? API : `${API}?version=${encodeURIComponent(version)}`);
  const pub = response.publication;
  if (pub && (!SHA.test(pub.version) || (version != null && pub.version !== version) || pub.paragraph_count < 1 || pub.paragraph_count > 256 || pub.entry_points.length > 12)) throw new Error("历史版本超出当前阅读范围，请刷新后重试。");
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

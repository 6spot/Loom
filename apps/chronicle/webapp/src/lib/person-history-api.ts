import { ApiError, fetchJSON } from "./api";

const SHA256 = /^[0-9a-f]{64}$/;
const PERSON_PARAGRAPH = /^pp_[0-9a-f]{24}$/;

export type PersonHistoryMappingStatus = "mapped" | "ambiguous" | "unmapped";
export type PersonHistoryCertainty = "clear" | "uncertain";
export type PersonHistoryDimension =
  | "office"
  | "title"
  | "allegiance"
  | "action"
  | "related_person"
  | "related_place";
export type PersonHistoryQualification =
  | "ordinary"
  | "recommendation"
  | "self_designation"
  | "posthumous"
  | "reported";

export interface PersonHistoryDate {
  readonly text?: string | null;
  readonly certainty?: PersonHistoryCertainty | null;
  readonly precision?: string | null;
  readonly [key: string]: unknown;
}

export interface PersonHistoryCoverage {
  readonly statement?: string | null;
  readonly exhaustive?: boolean;
  readonly [key: string]: unknown;
}

export interface PersonHistoryRelatedObject {
  readonly id: string;
  readonly canonical_id?: string | null;
  readonly kind?: string | null;
  readonly name?: string | null;
  readonly title?: string | null;
}

export interface PersonHistoryMappingTarget {
  readonly person_phase_id: string;
  readonly mapping_no: number;
  readonly status: PersonHistoryMappingStatus;
  readonly mapping_status: PersonHistoryMappingStatus;
  readonly version: string;
  readonly paragraph_id: string;
  readonly phase_id: string | null;
  readonly position_id?: string;
}

export interface PersonHistoryPhase {
  readonly id: string;
  readonly phase_id: string;
  readonly label?: string | null;
  readonly year?: number | null;
  readonly period?: string | null;
  readonly time_precision?: string | null;
  readonly relation_to_previous?: string | null;
  readonly mapping_status: PersonHistoryMappingStatus;
  readonly mapping_reason: string;
  readonly mapping_position_ids: readonly string[];
  readonly mapping?: {
    readonly status: PersonHistoryMappingStatus;
    readonly reason: string;
    readonly targets: readonly PersonHistoryMappingTarget[];
  };
  readonly mapping_targets?: readonly PersonHistoryMappingTarget[];
}

export interface PersonHistoryMappingMatch {
  readonly phase_id: string;
  readonly person_phase_id: string;
  readonly status: PersonHistoryMappingStatus;
  readonly mapping_status: PersonHistoryMappingStatus;
  readonly reason: string;
  readonly targets: readonly PersonHistoryMappingTarget[];
  readonly mapping_targets?: readonly PersonHistoryMappingTarget[];
}

export interface PersonHistoryMapping {
  readonly status: PersonHistoryMappingStatus;
  readonly reason: string;
  readonly request: {
    readonly version: string;
    readonly paragraph_id: string;
    readonly phase_id?: string | null;
  };
  readonly matches: readonly PersonHistoryMappingMatch[];
}

export interface PersonHistoryConclusion {
  readonly id: string;
  readonly person_id: string;
  readonly dimension: PersonHistoryDimension;
  readonly phase_ids: readonly string[];
  readonly text?: string | null;
  readonly value?: string | null;
  readonly certainty: PersonHistoryCertainty;
  readonly qualification: PersonHistoryQualification;
  readonly event_id?: string | null;
  readonly related_entity_ids: readonly string[];
  readonly related_objects: readonly PersonHistoryRelatedObject[];
  readonly evidence_ids: readonly string[];
  readonly evidence_count: number;
}

export interface PersonHistoryEvidence {
  readonly id: string;
  readonly evidence_id: string;
  readonly relation?: string | null;
  readonly attribution?: string | null;
  readonly note?: string | null;
  readonly source_id?: string | null;
  readonly publication_id: string;
  readonly source_title?: string | null;
  readonly anchor_id: string;
  readonly quote?: string | null;
  readonly start?: number | null;
  readonly end?: number | null;
  readonly source?: {
    readonly publication_id: string;
    readonly anchor_id: string;
    readonly path?: string;
  };
}

export interface PersonHistorySegment {
  readonly text: string;
  readonly conclusion_ids: readonly string[];
  readonly event_id?: string | null;
  readonly related_entity_ids: readonly string[];
  readonly related_objects: readonly PersonHistoryRelatedObject[];
  readonly states: readonly PersonHistoryConclusion[];
  readonly actions: readonly PersonHistoryConclusion[];
}

export interface PersonHistoryParagraph {
  readonly id: string;
  readonly paragraph_id: string;
  readonly ordinal: number;
  readonly phase_id: string;
  readonly phase: PersonHistoryPhase;
  readonly segments: readonly PersonHistorySegment[];
  readonly text: string;
  readonly conclusion_ids: readonly string[];
  readonly states: readonly PersonHistoryConclusion[];
  readonly actions: readonly PersonHistoryConclusion[];
  readonly related_entity_ids: readonly string[];
  readonly related_objects: readonly PersonHistoryRelatedObject[];
}

export interface PersonHistoryPublication {
  readonly person_history_version: string;
  readonly publication_version: string;
  readonly version_sha: string;
  readonly catalog_sha: string;
  readonly context_sha256: string;
  readonly source_publication_ids: readonly string[];
  readonly source_count: number;
  readonly coverage: PersonHistoryCoverage;
  readonly source_coverage?: PersonHistoryCoverage;
  readonly overview?: string | null;
  readonly reviewed_overview?: string | null;
  readonly birth?: PersonHistoryDate | null;
  readonly death?: PersonHistoryDate | null;
  readonly time_precision?: {
    readonly birth?: string;
    readonly death?: string;
    readonly phases?: string;
  };
  readonly phases: readonly PersonHistoryPhase[];
  readonly first_paragraph?: PersonHistoryParagraph;
  readonly first_paragraph_id: string;
  readonly paragraph_count: number;
  readonly conclusion_count: number;
  readonly published_at?: string | null;
  readonly publication_sequence?: number;
  readonly main_history_mapping?: PersonHistoryMapping | null;
  readonly mapping?: PersonHistoryMapping | null;
}

export interface PersonHistoryMetadataResponse {
  readonly schema: "chronicle.person-history-metadata" | string;
  readonly version: string;
  readonly person_id: string;
  readonly person: { readonly id: string; readonly name?: string | null; readonly kind: "person" | string };
  readonly status: "empty" | "published" | string;
  readonly empty: boolean;
  readonly publication: PersonHistoryPublication | null;
  readonly history?: PersonHistoryPublication | null;
  readonly metadata?: PersonHistoryPublication | null;
}

export interface PersonHistoryPageResponse {
  readonly schema: "chronicle.person-history-page" | string;
  readonly version: string;
  readonly person_id: string;
  readonly person_history_version: string;
  readonly publication_version: string;
  readonly paragraphs: readonly PersonHistoryParagraph[];
  readonly start: number;
  readonly total: number;
  readonly returned: number;
  readonly first_paragraph_id: string | null;
  readonly last_paragraph_id: string | null;
  readonly previous_start: number | null;
  readonly next_start: number | null;
  readonly has_more: boolean;
}

export interface PersonHistoryConclusionResponse {
  readonly schema: "chronicle.person-history-conclusion" | string;
  readonly version: string;
  readonly person_id: string;
  readonly person_history_version: string;
  readonly publication_version: string;
  readonly conclusion: PersonHistoryConclusion & { readonly evidence?: readonly PersonHistoryEvidence[] };
  readonly source_citations?: readonly PersonHistoryEvidence[];
}

export interface MainHistoryLocator {
  readonly version: string;
  readonly paragraphId: string;
  readonly phaseId?: string | null;
}

export interface PersonHistoryPageQuery {
  readonly start?: number;
  readonly limit?: number;
  readonly at?: string;
  readonly signal?: AbortSignal;
}

const API_PREFIX = "/api/v1/public/entities";

function entityPath(personId: string): string {
  if (!personId.trim()) throw new Error("人物标识不能为空。");
  return `${API_PREFIX}/${encodeURIComponent(personId)}/history`;
}

function fixedVersion(version: string, label = "人物生平版本"): string {
  if (!SHA256.test(version)) throw new Error(`${label}无效。`);
  return version;
}

export function isPersonHistoryVersion(value: string | null | undefined): value is string {
  return typeof value === "string" && SHA256.test(value);
}

export function isPersonHistoryParagraph(value: string | null | undefined): value is string {
  return typeof value === "string" && PERSON_PARAGRAPH.test(value);
}

export function personHistoryMetadataPath(
  personId: string,
  options: { readonly personVersion?: string | null; readonly mainHistory?: MainHistoryLocator | null } = {},
): string {
  const params = new URLSearchParams();
  const personVersion = options.personVersion ?? null;
  if (options.mainHistory) {
    params.set("version", fixedVersion(options.mainHistory.version, "主历史版本"));
    if (!options.mainHistory.paragraphId.trim()) throw new Error("主历史段落不能为空。");
    params.set("paragraph_id", options.mainHistory.paragraphId);
    if (options.mainHistory.phaseId) params.set("phase_id", options.mainHistory.phaseId);
    if (personVersion !== null) params.set("person_version", fixedVersion(personVersion));
  } else if (personVersion !== null) {
    params.set("person_version", fixedVersion(personVersion));
  }
  const suffix = params.toString();
  return `${entityPath(personId)}${suffix ? `?${suffix}` : ""}`;
}

export function personHistoryParagraphsPath(
  personId: string,
  version: string,
  query: Omit<PersonHistoryPageQuery, "signal"> = {},
): string {
  const params = new URLSearchParams({ version: fixedVersion(version), limit: String(query.limit ?? 50) });
  if (query.start !== undefined) params.set("start", String(query.start));
  if (query.at !== undefined) params.set("at", query.at);
  return `${entityPath(personId)}/paragraphs?${params.toString()}`;
}

export function personHistoryConclusionPath(personId: string, version: string, conclusionId: string): string {
  if (!conclusionId.trim()) throw new Error("人物生平结论不能为空。");
  return `${entityPath(personId)}/conclusions/${encodeURIComponent(conclusionId)}?version=${encodeURIComponent(fixedVersion(version))}`;
}

function validateMetadata(
  result: PersonHistoryMetadataResponse,
  personId: string,
  requestedVersion?: string | null,
): PersonHistoryMetadataResponse {
  if (result.person_id !== personId || result.person?.id !== personId) throw new Error("人物资料与当前页面不一致。");
  if (result.status === "published" && result.publication) {
    const publication = result.publication;
    if (publication.person_history_version !== publication.publication_version
      || !isPersonHistoryVersion(publication.person_history_version)
      || (requestedVersion !== undefined && requestedVersion !== null && publication.person_history_version !== requestedVersion)
      || !Array.isArray(publication.phases)) {
      throw new Error("人物生平版本资料不完整，请刷新后重试。");
    }
  }
  return result;
}

export async function loadPersonHistoryMetadata(
  personId: string,
  options: { readonly personVersion?: string | null; readonly mainHistory?: MainHistoryLocator | null } = {},
  signal?: AbortSignal,
): Promise<PersonHistoryMetadataResponse> {
  const path = personHistoryMetadataPath(personId, options);
  const result = await fetchJSON<PersonHistoryMetadataResponse>(path, { signal });
  return validateMetadata(result, personId, options.personVersion);
}

export async function loadPersonHistoryPage(
  personId: string,
  version: string,
  query: PersonHistoryPageQuery = {},
): Promise<PersonHistoryPageResponse> {
  const path = personHistoryParagraphsPath(personId, version, query);
  const result = await fetchJSON<PersonHistoryPageResponse>(path, { signal: query.signal });
  if (result.person_id !== personId
    || result.person_history_version !== version
    || result.publication_version !== version
    || !Number.isSafeInteger(result.start)
    || !Number.isSafeInteger(result.total)
    || !Array.isArray(result.paragraphs)
    || result.start + result.paragraphs.length > result.total) {
    throw new Error("人物经历与当前固定版本不一致。");
  }
  return result;
}

export async function loadPersonHistoryConclusion(
  personId: string,
  version: string,
  conclusionId: string,
  signal?: AbortSignal,
): Promise<PersonHistoryConclusionResponse> {
  const result = await fetchJSON<PersonHistoryConclusionResponse>(personHistoryConclusionPath(personId, version, conclusionId), { signal });
  if (result.person_id !== personId
    || result.person_history_version !== version
    || result.publication_version !== version
    || result.conclusion?.id !== conclusionId
    || !Array.isArray(result.conclusion?.evidence ?? result.source_citations)) {
    throw new Error("依据与当前固定人物生平版本不一致。");
  }
  return result;
}

export function mappingPhaseIds(mapping: PersonHistoryMapping | null | undefined): readonly string[] {
  if (!mapping || mapping.status === "unmapped") return [];
  return [...new Set(mapping.matches.map((match) => match.phase_id).filter(Boolean))];
}

export function metadataMapping(response: PersonHistoryMetadataResponse | null | undefined): PersonHistoryMapping | null {
  return response?.publication?.main_history_mapping ?? response?.publication?.mapping ?? null;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && error.code === "not_found";
}


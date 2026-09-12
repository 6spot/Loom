// Chronicle 第三轮人物阶段资料共享 DTO 与审核类型（C2-R3-T01）。
//
// 与 Chronicle ingestion 的 chronicle-person-state-v0.1.schema.json、0.3
// candidate/artifact schema 及 persistence 层的 person_state_contract.py
// 一一对应（浏览器不经 DB/artifact authority）。这些类型只描述服务端已编译
// 的结果：canonical ID、hash、坐标、cursor、item_id 与 candidate_key 都由
// 程序计算；浏览器不重新判定 certainty，也不按状态字段猜颜色。
//
// certainty 只来自固定 publication version 中已审核的证据：模型 confidence
// 不参与显示判定。行政归属（administration）与实际控制（control）是分开
// 的地点维度，不能互相推导。
//
// 本模块不接 App/router；T02-T15 直接消费这些类型。

export const PERSON_STATE_SCHEMA_ID =
  "https://loom.local/chronicle/schemas/chronicle-person-state-v0.1.schema.json";

/** Engineering envelope mirrored from person_state_contract.PersonStateLimits. */
export const PERSON_STATE_LIMITS = {
  maxPhases: 512,
  maxFacts: 512,
  maxAssertions: 1024,
  maxPhasesPerUnit: 8,
  maxSourceSelections: 16,
  summaryMaxItems: 3,
  pageMinLimit: 1,
  pageMaxLimit: 50,
  evidencePageMaxDescriptors: 50,
  summaryMaxBytes: 128 * 1024,
  detailMaxBytes: 128 * 1024,
  evidenceMaxBytes: 64 * 1024,
  compiledItemMaxBytes: 64 * 1024,
  jsonMaxBytes: 8 * 1024 * 1024,
} as const;

export type Certainty = "clear" | "uncertain";
export type StateDimension = "office" | "title" | "affiliation";
export type PlaceDimension = "administration" | "control";
export type PersonPhaseMode = "single" | "process" | "ambiguous" | "unknown";
export type StateOperation = "start" | "end" | "attest";
export type Qualification =
  | "ordinary"
  | "recommendation"
  | "self_designation"
  | "posthumous"
  | "reported";
export type Attribution = "narrator" | "quotation" | "annotation" | "hearsay";
export type Assessment = "supported" | "uncertain" | "disputed" | "rejected";
export type PredictedEffect = "current" | "prior" | "ended" | "none";
export type ReasonCode =
  | "tenure_unproven"
  | "order_unknown"
  | "source_disagreement"
  | "attribution_uncertain"
  | "evidence_uncertain"
  | "phase_not_reached"
  | "phase_not_begun";

export const STATE_DIMENSIONS: readonly StateDimension[] = ["office", "title", "affiliation"];
export const PLACE_DIMENSIONS: readonly PlaceDimension[] = ["administration", "control"];
export const REASON_CODES: readonly ReasonCode[] = [
  "tenure_unproven",
  "order_unknown",
  "source_disagreement",
  "attribution_uncertain",
  "evidence_uncertain",
  "phase_not_reached",
  "phase_not_begun",
];
export const ASSESSMENTS: readonly Assessment[] = [
  "supported",
  "uncertain",
  "disputed",
  "rejected",
];

/** Stable {stream_id, catalog_sha, unit_id} locator; batch queries never fan out. */
export interface PersonStateLocator {
  readonly stream_id: string;
  readonly catalog_sha: string;
  readonly unit_id: string;
}

export interface PhaseSummary {
  readonly phase_id: string;
  readonly label: string;
  readonly ordinal: number;
  readonly mode: PersonPhaseMode;
}

export interface SourceFactRef {
  readonly chapter_publication_id: string;
  readonly chapter_id: string;
  readonly revision_id: string;
  readonly fact_ref: string;
  readonly claim_refs: readonly string[];
  readonly phase_id: string;
}

export interface StateItem {
  readonly item_id: string;
  readonly person_id: string;
  readonly dimension: StateDimension;
  readonly value: string | null;
  readonly relation: "serves" | "attached_to" | null;
  readonly target: string | null;
  readonly target_id: string | null;
  readonly qualification: Qualification;
  readonly certainty: Certainty;
  readonly reason_codes: readonly ReasonCode[];
  readonly reason_text: string;
  readonly phase_ids: readonly string[];
  readonly current: boolean;
  readonly source_facts: readonly SourceFactRef[];
  readonly evidence_count: number;
  readonly evidence_cursor: string | null;
}

export interface StateChange {
  readonly item_id: string;
  readonly person_id: string;
  readonly dimension: StateDimension;
  readonly value: string | null;
  readonly relation: "serves" | "attached_to" | null;
  readonly target: string | null;
  readonly operation: StateOperation;
  readonly from_phase_id: string | null;
  readonly to_phase_id: string;
  readonly certainty: Certainty;
  readonly reason_codes: readonly ReasonCode[];
  readonly source_facts: readonly SourceFactRef[];
}

export interface PersonSummary {
  readonly person_id: string;
  readonly name: string;
  readonly importance: "primary" | "other";
  readonly phase_mode: PersonPhaseMode;
  readonly certainty: Certainty;
  readonly identities: readonly StateItem[];
  readonly identity_count: number;
  readonly has_more_identities: boolean;
  readonly identity_cursor: string | null;
  readonly changes: readonly StateChange[];
  readonly change_count: number;
  readonly has_more_changes: boolean;
  readonly change_cursor: string | null;
  readonly reason_codes: readonly ReasonCode[];
}

export interface UnitPeoplePage {
  readonly stream_id: string;
  readonly unit_id: string;
  readonly catalog_sha: string;
  readonly publication_id: string;
  readonly state_manifest_sha: string;
  readonly phase_mode: PersonPhaseMode;
  readonly phases: readonly PhaseSummary[];
  readonly limit: number;
  readonly people: readonly PersonSummary[];
  readonly people_count: number;
  readonly next_cursor: string | null;
  readonly has_more: boolean;
}

export interface PersonStatePage {
  readonly stream_id: string;
  readonly unit_id: string;
  readonly catalog_sha: string;
  readonly publication_id: string;
  readonly state_manifest_sha: string;
  readonly person_id: string;
  readonly section: "identities" | "changes";
  readonly phase_id: string | null;
  readonly phases: readonly PhaseSummary[];
  readonly items: readonly StateItem[];
  readonly changes: readonly StateChange[];
  readonly item_count: number;
  readonly limit: number;
  readonly next_cursor: string | null;
  readonly has_more: boolean;
}

export interface EvidenceDescriptor {
  readonly descriptor_id: string;
  readonly source_publication_id: string;
  readonly anchor_id: string;
  readonly quote: string;
  readonly quote_sha256: string;
  readonly attribution: Attribution;
  readonly source_title: string;
  readonly phase_id: string;
  readonly relation: "support" | "supplement" | "contradict" | "background";
}

export interface StateEvidencePage {
  readonly stream_id: string;
  readonly unit_id: string;
  readonly catalog_sha: string;
  readonly publication_id: string;
  readonly state_manifest_sha: string;
  readonly item_id: string;
  readonly section: "evidence";
  readonly phase_id: string | null;
  readonly descriptors: readonly EvidenceDescriptor[];
  readonly descriptor_count: number;
  readonly limit: number;
  readonly next_cursor: string | null;
  readonly has_more: boolean;
}

export interface PlaceStateItem {
  readonly item_id: string;
  readonly place_id: string;
  readonly name: string;
  readonly dimension: PlaceDimension;
  readonly value: string | null;
  readonly controller: string | null;
  readonly certainty: Certainty;
  readonly reason_codes: readonly ReasonCode[];
  readonly reason_text: string;
  readonly phase_ids: readonly string[];
  readonly current: boolean;
  readonly source_facts: readonly SourceFactRef[];
  readonly evidence_count: number;
  readonly evidence_cursor: string | null;
}

export interface PlaceStatePage {
  readonly stream_id: string;
  readonly unit_id: string;
  readonly catalog_sha: string;
  readonly publication_id: string;
  readonly state_manifest_sha: string;
  readonly section: "places";
  readonly phases: readonly PhaseSummary[];
  readonly places: readonly PlaceStateItem[];
  readonly limit: number;
  readonly next_cursor: string | null;
  readonly has_more: boolean;
}

// ---------------------------------------------------------------------------
// Review surfaces (person-state-reading.md §5)
// ---------------------------------------------------------------------------

export type ReviewScope = "resolution" | "person_state" | "chapter_content" | "all";
export const REVIEW_SCOPES: readonly ReviewScope[] = ["resolution", "person_state", "chapter_content", "all"];
export const DEFAULT_REVIEW_SCOPE: ReviewScope = "resolution";

export interface ReviewCandidate {
  readonly candidate_key: string;
  readonly kind: "phase" | "phase_order" | "unit_phase" | "fact" | "continuity" | "disagreement";
  readonly chapter_id: string;
  readonly item_ref: string;
  readonly person_id: string | null;
  readonly person_name: string | null;
  readonly dimension: StateDimension | PlaceDimension | null;
  readonly value: string | null;
  readonly relation: string | null;
  readonly target: string | null;
  readonly operation: StateOperation | null;
  readonly qualification: Qualification | null;
  readonly phase_refs: readonly string[];
  readonly predicted_effect: PredictedEffect;
  readonly assessment_default: Assessment;
  readonly allowed_assessments: readonly Assessment[];
  readonly source_label: string;
  readonly quote: string;
  readonly attribution: Attribution;
  readonly reason_codes: readonly ReasonCode[];
}

export interface ReviewPackage {
  readonly schema: "chronicle.person-state-review";
  readonly version: "0.1";
  readonly review_id: string;
  readonly plan_fingerprint: string;
  readonly scope: "person_state";
  readonly review_mode: "chapter_state_evidence";
  readonly chapter_id: string;
  readonly catalog_sha: string;
  readonly candidates: readonly ReviewCandidate[];
  readonly candidate_count: number;
  readonly limit: number;
  readonly cursor: string | null;
  readonly next_cursor: string | null;
  readonly has_more: boolean;
  readonly default_assessment: Assessment;
}

export interface AssessmentOverride {
  readonly candidate_key: string;
  readonly assessment: Assessment;
  readonly rationale: string;
}

export interface AssessmentOverlay {
  readonly plan_fingerprint: string;
  readonly default_assessment: Assessment;
  readonly overrides: readonly AssessmentOverride[];
  readonly rationale: string;
}

// ---------------------------------------------------------------------------
// Fixed error codes and type guards
// ---------------------------------------------------------------------------

export type PersonStateErrorCode =
  | "bad_request"
  | "not_found"
  | "source_missing"
  | "source_mismatch";

export const PERSON_STATE_ERROR_STATUS: Readonly<Record<PersonStateErrorCode, number>> = {
  bad_request: 400,
  not_found: 404,
  source_missing: 409,
  source_mismatch: 409,
};

/** The omitted parameter keeps the legacy resolution default (contract §5.1). */
export function normalizeReviewScope(value: string | null | undefined): ReviewScope {
  if (value === null || value === undefined || value === "") return DEFAULT_REVIEW_SCOPE;
  if (!(REVIEW_SCOPES as readonly string[]).includes(value)) {
    throw new Error(`review_scope must be one of ${REVIEW_SCOPES.join("|")}, got ${value}`);
  }
  return value as ReviewScope;
}

/** ``all`` covers resolution + person_state + narrative + chapter_content; the legacy resolution
 * scope covers the existing facts/prose (narrative) entry. */
export function reviewScopeCovers(
  scope: string | null | undefined,
  target: "resolution" | "person_state" | "narrative" | "chapter_content",
): boolean {
  const normalized = normalizeReviewScope(scope);
  if (normalized === "all") return true;
  if (normalized === "person_state" || normalized === "chapter_content") return target === normalized;
  return target === "resolution" || target === "narrative";
}

const LOCATOR_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const UNIT_ID = /^ru_[0-9a-f]{24}$/;

export function isPersonStateLocator(value: unknown): value is PersonStateLocator {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.stream_id === "string" &&
    LOCATOR_UUID.test(candidate.stream_id) &&
    typeof candidate.catalog_sha === "string" &&
    SHA256.test(candidate.catalog_sha) &&
    typeof candidate.unit_id === "string" &&
    UNIT_ID.test(candidate.unit_id)
  );
}

export function isCertainty(value: unknown): value is Certainty {
  return value === "clear" || value === "uncertain";
}

export function isReasonCode(value: unknown): value is ReasonCode {
  return typeof value === "string" && (REASON_CODES as readonly string[]).includes(value);
}

/** Browser never re-derives certainty; this only guards server output. */
export function isStateItem(value: unknown): value is StateItem {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.item_id === "string" &&
    (STATE_DIMENSIONS as readonly string[]).includes(candidate.dimension as string) &&
    isCertainty(candidate.certainty) &&
    Array.isArray(candidate.reason_codes) &&
    candidate.reason_codes.every(isReasonCode)
  );
}

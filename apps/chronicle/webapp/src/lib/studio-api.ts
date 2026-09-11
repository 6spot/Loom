// Chronicle Studio HTTP client for C1-T10/T11.
//
// The Rust server remains the authentication/authorization boundary. This
// module only transports the current tab-session Basic auth header to the
// privileged same-origin `/api/v1/studio/*` API and never touches DB/files
// directly. Job detail is the server's safe projection: model prompts, raw
// responses and candidates are intentionally not part of these types.

export class StudioApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: CanonicalIdentityConflictDetails;

  constructor(status: number, code: string, message: string, details?: CanonicalIdentityConflictDetails) {
    super(message);
    this.name = "StudioApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export type JobStatus = "queued" | "running" | "needs_review" | "failed" | "cancelled" | "completed";
export type StageStatus = "pending" | "running" | "needs_review" | "failed" | "skipped" | "completed";
export type ReviewStatus = "open" | "resolved" | "dismissed";
export type ReviewLinkKind = "entity" | "event";
export type EntityReviewDecision = "same_entity" | "not_same" | "uncertain";
export type EventReviewDecision = "same_occurrence" | "related_occurrence" | "not_same" | "uncertain";
export type ReviewDecision = EntityReviewDecision | EventReviewDecision | "approve" | "reject";

export interface DocumentSummary {
  document_id: string;
  title: string;
  created_at: string | null;
  revision_count: number;
  active_revision_no: number | null;
  active_source_sha256: string | null;
}

export interface Revision {
  revision_id: string;
  document_id: string;
  revision_no: number;
  status: "active" | "superseded";
  filename: string;
  source_media_type: string;
  source_sha256: string;
  source_bytes: number;
  content_chars: number;
  language: string | null;
  source_label: string | null;
  storage_key: string;
  storage_status: string;
  supersedes_revision_id: string | null;
  created_at: string | null;
  duplicate?: boolean;
}

export interface DocumentDetail {
  document_id: string;
  title: string;
  created_at?: string | null;
  revision_count: number;
  active_revision: Revision | null;
}

export interface JobSummary {
  job_id: string;
  revision_id: string;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  lease_owner: string | null;
  lease_expires_at: string | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_stages: number;
  chunk_count: number;
}

export interface RunAttemptMeta {
  kind?: string;
  prompt_sha256?: string;
  raw_response_sha256?: string;
  parse_error?: string;
  validation?: unknown;
}

export interface RunMeta {
  extraction_version?: string;
  contract_version?: string;
  prompt_version?: string;
  model_version?: string;
  attempt_count?: number;
  accepted?: boolean;
  error?: string;
  authoritative?: boolean;
  authority_note?: string;
  attempts?: RunAttemptMeta[];
}

export interface ChunkRun {
  run_id: string;
  attempt: number;
  status: string;
  worker: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  meta: RunMeta;
}

export interface JobChunk {
  chunk_id: string;
  section_id: string | null;
  chunk_index: number;
  status: string;
  attempt: number;
  max_attempts: number;
  source_start: number;
  source_end: number;
  source_sha256: string;
  content_sha256: string;
  runs: ChunkRun[];
}

export interface JobStage {
  stage: string;
  status: StageStatus;
  attempt: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobReviewSummary {
  review_id: string;
  kind: string;
  status: string;
  chunk_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
}

export interface JobOutputSummary {
  output_id: string;
  artifact_type: string;
  artifact_sha256: string;
  created_at: string | null;
}

export interface JobDetail {
  job_id: string;
  revision_id: string;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  lease_owner: string | null;
  lease_expires_at: string | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
  open_reviews: number;
  stages: JobStage[];
  chunks: JobChunk[];
  reviews: JobReviewSummary[];
  outputs: JobOutputSummary[];
}

export interface ReviewDocumentContext {
  document_id: string;
  title: string;
  revision_no: number;
  filename: string;
  source_sha256: string;
  language: string | null;
  source_label: string | null;
}

export interface ReviewRef {
  bundle: string;
  ref: string;
}

export interface ReviewCandidateMember {
  candidate_key: string;
  resolution_sha256: string;
  candidate_id: string;
  link_kind: ReviewLinkKind;
  left: ReviewRef;
  right: ReviewRef;
  signals: string[];
}

export interface ReviewSuggestion {
  decision: string | null;
  confidence: number | null;
  rationale: string | null;
  signals: unknown[];
}

export interface ReviewGroupDecisionInput {
  review_group_id: string;
  decision: ReviewDecision;
  confidence: number;
  rationale: string;
}

export interface ReviewChosenDecision {
  decision: ReviewDecision;
  confidence: number;
  rationale: string;
  group_decisions?: ReviewGroupDecisionInput[];
}

export interface ReviewRecordContext {
  bundle: string;
  ref: string;
  source_title?: string | null;
  source_ref?: string | null;
  record: {
    kind?: ReviewLinkKind;
    type?: string | null;
    name?: string | null;
    title?: string | null;
    aliases?: unknown[];
    mentions?: unknown[];
    time?: unknown;
    participants?: unknown[];
    places?: unknown[];
  };
}

export interface ReviewGroupDetail {
  review_group_id: string;
  member_count: number;
  signals: string[];
  right_contexts: ReviewRecordContext[];
}

export interface CanonicalIdentityConflictDetails {
  review_id: string;
  canonical_ids: string[];
  canonical_entities: Array<{
    canonical_id: string;
    names: string[];
    contexts: ReviewRecordContext[];
  }>;
  review_group_ids: string[];
  candidate_keys: string[];
  proposed_candidate_keys: string[];
  incoming_refs: ReviewRef[];
  incoming_contexts: ReviewRecordContext[];
  published_refs: Array<ReviewRef & { canonical_id: string }>;
  review_groups: Array<{
    review_group_id: string;
    candidate_keys: string[];
    incoming_refs: ReviewRef[];
    right_contexts: ReviewRecordContext[];
  }>;
}

export interface ReviewSummary {
  review_id: string;
  job_id: string;
  chunk_id: string | null;
  kind: string;
  status: ReviewStatus;
  created_at: string | null;
  resolved_at: string | null;
  job_status: JobStatus;
  revision_id: string;
  document: ReviewDocumentContext;
  scope: "resolution" | "narrative";
  narrative_kind?: "facts" | "prose";
  candidate_sha?: string;
  link_kind: ReviewLinkKind;
  review_subject_id?: string | null;
  review_subject_version?: string | null;
  member_count?: number;
  group_count?: number;
  groups?: unknown[];
  members?: ReviewCandidateMember[];
  candidate_id: string;
  resolution_sha256: string;
  blocking: boolean;
  allowed_decisions: ReviewDecision[];
  left: ReviewRef;
  right: ReviewRef;
  left_label?: string | null;
  right_label?: string | null;
  suggestion: ReviewSuggestion;
  decision: ReviewChosenDecision | null;
  plan_fingerprint?: string | null;
}

export interface ReviewDetail extends ReviewSummary {
  narrative?: import("./narrative-types").NarrativeReviewData;
  left_context: ReviewRecordContext;
  right_context: ReviewRecordContext;
  left_contexts?: ReviewRecordContext[];
  right_contexts?: ReviewRecordContext[];
  review_groups?: ReviewGroupDetail[];
  job_open_resolution_reviews: number;
  review_mode?: "chapter_pair" | "published_batch" | string | null;
  source_contexts?: {
    total: number;
    href: string;
    items: SourceContextDescriptor[];
  };
  source_entry?: {
    contexts_href: string;
    source_href_template: string;
    revision_id: string;
    source_sha256: string | null;
  };
}

export type SourceEvidenceKind =
  | "direct_claim"
  | "mention"
  | "record_source"
  | "event_context"
  | "translation";

export interface SourceAnchorSummary {
  anchor_id: string;
  chapter_id: string | null;
  start: number | null;
  end: number | null;
  quote_sha256: string | null;
}

export interface SourceContextDescriptor {
  context_id: string;
  bundle: string;
  bundle_sha256: string | null;
  record_ref: string;
  link_kind: ReviewLinkKind | string;
  job_id: string;
  revision_id: string;
  chapter_id: string | null;
  chapter_index: number | null;
  chapter_title: string | null;
  artifact_sha256: string | null;
  source_title: string | null;
  source_sha256: string | null;
  evidence_kinds: SourceEvidenceKind[];
  available: boolean;
  unavailable_reason: string | null;
  anchor_count: number;
  anchors: SourceAnchorSummary[];
}

export interface ReviewContextsResponse {
  schema: "chronicle.review-source-contexts";
  version: string;
  review_id: string;
  group_id: string | null;
  total: number;
  items: SourceContextDescriptor[];
  has_more: boolean;
  next_cursor: string | null;
}

export interface ReviewSourceSegment {
  text: string;
  highlight: boolean;
}

export interface ReviewSourceResponse {
  schema: "chronicle.review-source";
  version: string;
  review_id: string;
  anchor_id: string;
  view: "window" | "chapter";
  revision_id: string;
  source_sha256: string;
  chapter_id: string;
  bundle: string;
  record_ref: string;
  bounds: {
    start: number;
    end: number;
    slice_start: number;
    slice_end: number;
    chapter_start: number;
    chapter_end: number;
    chapter_length: number;
  };
  source_hash: string;
  chapter_hash: string;
  text: string;
  segments: ReviewSourceSegment[];
  has_more: boolean;
  next_cursor: string | null;
}

interface DocumentsResponse {
  schema: "chronicle.document-list";
  version: string;
  documents: DocumentSummary[];
}

interface DocumentResponse {
  schema: "chronicle.document";
  version: string;
  document: DocumentDetail;
}

interface RevisionListResponse {
  schema: "chronicle.revision-list";
  version: string;
  document_id: string;
  revisions: Revision[];
}

interface RevisionResponse {
  schema: "chronicle.revision";
  version: string;
  revision: Revision;
  locator?: unknown;
}

interface JobsResponse {
  schema: "chronicle.job-list";
  version: string;
  jobs: JobSummary[];
}

interface JobResponse {
  schema: "chronicle.job";
  version: string;
  job: JobDetail;
}

export interface ReviewPageQuery {
  status?: ReviewStatus | "all";
  jobId?: string | null;
  linkKind?: ReviewLinkKind | null;
  limit?: number;
  cursor?: string | null;
}

export interface ReviewPage {
  schema: "chronicle.studio-review-page";
  version: string;
  query: {
    status: ReviewStatus | "all";
    job_id: string | null;
    link_kind: ReviewLinkKind | null;
    limit: number;
  };
  items: ReviewSummary[];
  next_cursor: string | null;
  open_count: number;
  observed_at: string;
  plan_fingerprint: string;
}

interface ReviewResponse {
  schema: "chronicle.review";
  version: string;
  review: ReviewDetail;
}

function authHeaders(auth: string | null, extra?: HeadersInit): Headers {
  const headers = new Headers(extra ?? {});
  headers.set("Accept", "application/json");
  if (auth) headers.set("Authorization", auth);
  return headers;
}

async function parseResponse<T>(response: Response): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new StudioApiError(response.status, "invalid_response", `Studio API returned HTTP ${response.status}`);
  }
  if (!response.ok) {
    const error = (payload as { error?: {
      code?: string; message?: string; details?: CanonicalIdentityConflictDetails;
    } })?.error;
    throw new StudioApiError(
      response.status,
      error?.code ?? "request_failed",
      error?.message ?? `Studio API returned HTTP ${response.status}`,
      error?.details,
    );
  }
  return payload as T;
}

export async function studioRequest<T>(auth: string | null, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: authHeaders(auth, init.headers),
  });
  return parseResponse<T>(response);
}

export function jobIsLive(status: JobStatus): boolean {
  return status === "queued" || status === "running" || status === "needs_review";
}

export function mediaTypeForUpload(filename: string): string | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".txt")) return "text/plain";
  if (lower.endsWith(".md")) return "text/markdown";
  return null;
}

export function formatShortHash(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 16 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value;
}

export async function listDocuments(auth: string | null): Promise<DocumentSummary[]> {
  return (await studioRequest<DocumentsResponse>(auth, "/api/v1/studio/documents")).documents;
}

export async function createDocument(auth: string | null, title: string): Promise<DocumentDetail> {
  return (
    await studioRequest<DocumentResponse>(auth, "/api/v1/studio/documents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    })
  ).document;
}

export async function listRevisions(auth: string | null, documentId: string): Promise<Revision[]> {
  const path = `/api/v1/studio/documents/${encodeURIComponent(documentId)}/revisions`;
  return (await studioRequest<RevisionListResponse>(auth, path)).revisions;
}

export async function uploadRevision(
  auth: string | null,
  documentId: string,
  file: File,
  metadata: { language?: string; sourceLabel?: string } = {},
): Promise<Revision> {
  const mediaType = mediaTypeForUpload(file.name);
  if (!mediaType) throw new StudioApiError(400, "unsupported_file", "只支持 UTF-8 .txt 或 .md 文献");
  const params = new URLSearchParams({ filename: file.name });
  if (metadata.language?.trim()) params.set("language", metadata.language.trim());
  if (metadata.sourceLabel?.trim()) params.set("source_label", metadata.sourceLabel.trim());
  const path = `/api/v1/studio/documents/${encodeURIComponent(documentId)}/revisions?${params.toString()}`;
  return (
    await studioRequest<RevisionResponse>(auth, path, {
      method: "POST",
      headers: { "Content-Type": mediaType },
      body: file,
    })
  ).revision;
}

export async function listJobs(auth: string | null, status?: JobStatus): Promise<JobSummary[]> {
  const params = new URLSearchParams({ limit: "100", offset: "0" });
  if (status) params.set("status", status);
  return (await studioRequest<JobsResponse>(auth, `/api/v1/studio/jobs?${params.toString()}`)).jobs;
}

export async function getJob(auth: string | null, jobId: string): Promise<JobDetail> {
  return (await studioRequest<JobResponse>(auth, `/api/v1/studio/jobs/${encodeURIComponent(jobId)}`)).job;
}

export async function queueJob(auth: string | null, revisionId: string, maxAttempts = 3): Promise<JobDetail> {
  return (
    await studioRequest<JobResponse>(auth, "/api/v1/studio/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision_id: revisionId, max_attempts: maxAttempts }),
    })
  ).job;
}

export async function mutateJob(
  auth: string | null,
  jobId: string,
  action: "retry" | "resume" | "cancel",
): Promise<JobDetail> {
  const path = `/api/v1/studio/jobs/${encodeURIComponent(jobId)}/${action}`;
  return (await studioRequest<JobResponse>(auth, path, { method: "POST" })).job;
}

const REVIEWS_API = "/api/v1/studio/jobs/reviews";

export async function submitNarrativeDecision(auth: string | null, reviewId: string, payload: {
  candidate_sha: string; decision: "approve" | "reject"; rationale: string;
  content: import("./narrative-types").NarrativeContent; reviewed_conclusion_ids: string[];
}): Promise<ReviewDetail> {
  return (await studioRequest<ReviewResponse>(auth, `${REVIEWS_API}/${encodeURIComponent(reviewId)}/decision`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  })).review;
}

export interface NarrativeSourceChoices {
  catalog_sha: string | null;
  items: Array<{ publication_id: string; document_title: string; chapter_id: string; revision_no: number; title: string }>;
  has_more: boolean; offset: number;
}
export function listNarrativeSources(auth: string | null, offset = 0): Promise<NarrativeSourceChoices> {
  return studioRequest(auth, `/api/v1/studio/jobs/history/sources?limit=50&offset=${offset}`);
}
export async function queueNarrative(auth: string | null, catalogSha: string, publicationIds: string[]): Promise<JobDetail> {
  return (await studioRequest<JobResponse>(auth, "/api/v1/studio/jobs/history", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ catalog_sha: catalogSha, publication_ids: publicationIds }),
  })).job;
}

export async function listReviewPage(
  auth: string | null,
  query: ReviewPageQuery = {},
): Promise<ReviewPage> {
  const params = new URLSearchParams();
  params.set("status", query.status ?? "open");
  if (query.jobId) params.set("job_id", query.jobId);
  if (query.linkKind) params.set("link_kind", query.linkKind);
  params.set("limit", String(query.limit ?? 50));
  if (query.cursor) params.set("cursor", query.cursor);
  return studioRequest<ReviewPage>(auth, `${REVIEWS_API}?${params.toString()}`);
}

// Transitional wrapper (T09): traverse the keyset pages of the queue API so
// callers that have not been rewired to true pagination keep working. There
// is no second server-side pagination. T11 continuous-review pages read page
// by page via listReviewPage and no longer consume this wrapper; the export
// is retained (deprecated) because tests/studio-reviews.test.ts owns its
// traversal contract outside the T11 file scope.
// @deprecated Use listReviewPage with scope filters and next_cursor.
export async function listReviews(
  auth: string | null,
  status: ReviewStatus | "all" = "open",
): Promise<ReviewSummary[]> {
  const collected: ReviewSummary[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < 1000; page += 1) {
    const result = await listReviewPage(auth, { status, limit: 100, cursor });
    collected.push(...result.items);
    if (!result.next_cursor) return collected;
    cursor = result.next_cursor;
  }
  throw new StudioApiError(500, "review_page_overflow", "审核队列分页遍历超出上限");
}

export async function getReview(auth: string | null, reviewId: string): Promise<ReviewDetail> {
  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}`;
  return (await studioRequest<ReviewResponse>(auth, path)).review;
}

// C2-R1-T12 review evidence: frozen source-context descriptors and the
// exact source reader (window ±400 code points, chapter pages ≤16k). These
// transport the T10 backend DTOs only; the T11 draft/queue ownership stays
// in review-session.ts and the decision form.
export async function listReviewContexts(
  auth: string | null,
  reviewId: string,
  query: { groupId?: string | null; limit?: number; cursor?: string | null } = {},
): Promise<ReviewContextsResponse> {
  const params = new URLSearchParams();
  if (query.groupId) params.set("group_id", query.groupId);
  params.set("limit", String(query.limit ?? 50));
  if (query.cursor) params.set("cursor", query.cursor);
  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}/contexts?${params.toString()}`;
  return studioRequest<ReviewContextsResponse>(auth, path);
}

export async function listAllReviewContexts(
  auth: string | null,
  reviewId: string,
  query: { groupId?: string | null; limit?: number } = {},
): Promise<SourceContextDescriptor[]> {
  const collected: SourceContextDescriptor[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < 100; page += 1) {
    const result = await listReviewContexts(auth, reviewId, {
      groupId: query.groupId,
      limit: query.limit ?? 50,
      cursor,
    });
    collected.push(...result.items);
    if (!result.has_more || !result.next_cursor) return collected;
    cursor = result.next_cursor;
  }
  throw new StudioApiError(500, "context_page_overflow", "来源描述分页遍历超出上限");
}

export async function getReviewSourceWindow(
  auth: string | null,
  reviewId: string,
  anchorId: string,
): Promise<ReviewSourceResponse> {
  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}/sources/${encodeURIComponent(anchorId)}?view=window`;
  return studioRequest<ReviewSourceResponse>(auth, path);
}

export async function getReviewSourceChapterPage(
  auth: string | null,
  reviewId: string,
  anchorId: string,
  query: { cursor?: string | null; limit?: number } = {},
): Promise<ReviewSourceResponse> {
  const params = new URLSearchParams({ view: "chapter" });
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.limit != null) params.set("limit", String(query.limit));
  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}/sources/${encodeURIComponent(anchorId)}?${params.toString()}`;
  return studioRequest<ReviewSourceResponse>(auth, path);
}

/**
 * Stable request key: review/plan/context/artifact (review-workflow §§4–5).
 * The backend binds `context_id` only to `(review_id, bundle, ref)`, so the
 * artifact can change while context and anchor stay the same: the same
 * context/anchor with a new `artifact_sha256` is a different slot and must
 * never reuse or accept old-artifact material.
 */
export function evidenceRequestKey(
  reviewId: string,
  planFingerprint: string | null | undefined,
  contextId: string,
  anchorId: string,
  artifactSha256?: string | null,
): string {
  return `${reviewId}|${planFingerprint ?? "-"}|${contextId}|${anchorId}|${artifactSha256 || "-"}`;
}

// C2-R1-T12 stale-response guard (review-workflow §§4–5: a late response
// must never mix materials across anchors, groups or reviews).
//
// A panel/section issues one token per flight and invalidates the guard on
// every identity transition (anchor/context/review/group change). Only the
// token that is still current when its response lands may write state.
export interface EvidenceRequestGuard {
  issue(): number;
  invalidate(): void;
  isCurrent(token: number): boolean;
}

export function createEvidenceRequestGuard(): EvidenceRequestGuard {
  let epoch = 0;
  return {
    issue() {
      epoch += 1;
      return epoch;
    },
    invalidate() {
      epoch += 1;
    },
    isCurrent(token: number) {
      return token === epoch;
    },
  };
}

export async function submitReviewDecision(
  auth: string | null,
  reviewId: string,
  decision: ReviewDecision,
  rationale: string,
  confidence = 0.5,
  groupDecisions: ReviewGroupDecisionInput[] = [],
): Promise<ReviewDetail> {
  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}/decision`;
  const payload: {
    decision: ReviewDecision;
    rationale: string;
    confidence: number;
    group_decisions?: ReviewGroupDecisionInput[];
  } = { decision, rationale, confidence };
  if (groupDecisions.length) payload.group_decisions = groupDecisions;
  return (
    await studioRequest<ReviewResponse>(auth, path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  ).review;
}

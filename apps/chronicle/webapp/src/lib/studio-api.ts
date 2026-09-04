// Chronicle Studio HTTP client for C1-T10.
//
// The Rust server remains the authentication/authorization boundary. This
// module only transports the current tab-session Basic auth header to the
// privileged same-origin `/api/v1/studio/*` API and never touches DB/files
// directly. Job detail is the server's safe v0.2 projection: model prompts,
// raw responses and candidates are intentionally not part of these types.

export class StudioApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "StudioApiError";
    this.status = status;
    this.code = code;
  }
}

export type JobStatus = "queued" | "running" | "needs_review" | "failed" | "cancelled" | "completed";
export type StageStatus = "pending" | "running" | "needs_review" | "failed" | "skipped" | "completed";

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
    const error = (payload as { error?: { code?: string; message?: string } })?.error;
    throw new StudioApiError(
      response.status,
      error?.code ?? "request_failed",
      error?.message ?? `Studio API returned HTTP ${response.status}`,
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

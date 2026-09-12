// C2-R3-T10 source-reading person-state typed client.
//
// Browsers reach the source-reading person/state surfaces only through the
// Rust `/api/v1/public/reading-streams/...` boundary; the Python sidecar's
// `/v0/reading-streams/.../people` contracts stay the one read authority
// (`person-state-reading.md` §7). Every path carries the full
// `{stream_id, catalog_sha, unit_id}` locator plus the person/section bound
// cursor: the snapshot is part of the identity, so switching catalog or person
// never reuses another page.
//
// The types come from the T01 shared contract (`person-state-types.ts`); this
// module never re-derives certainty, never invents a simplified DTO and never
// reads the database. Abort and typed errors are surfaced explicitly so the
// caller can retry; a late response is never allowed to overwrite a newer one
// (the component layer owns the stale guard).
//
// File boundary (T10): this new module keeps the composite main-reading
// `HistoryLocator` (`history-api.ts`) separate from the source `PersonStateLocator`.

import {
  isPersonStateLocator,
  PERSON_STATE_LIMITS,
  type PersonStateLocator,
  type PersonStatePage,
  type StateEvidencePage,
  type UnitPeoplePage,
} from "./person-state-types";

export const PERSON_STATE_API_PREFIX = "/api/v1/public";

export class PersonStateApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "PersonStateApiError";
    this.status = status;
    this.code = code;
  }
}

/** Caller-initiated abort; never confused with a real network failure. */
export class PersonStateAbortError extends Error {
  constructor(message = "person-state request aborted") {
    super(message);
    this.name = "PersonStateAbortError";
  }
}

// ---------------------------------------------------------------------------
// Locator / parameter validation (fail before any URL exists)
// ---------------------------------------------------------------------------

const SHA256 = /^[0-9a-f]{64}$/;
// Canonical person ids are UUIDs today, but the read contract only requires a
// single safe path token; mirror the Rust `validated_id` segment rule instead
// of over-restricting the client relative to the server.
const PERSON_ID = /^[A-Za-z0-9_.:-]+$/;
const ITEM_ID = /^psi_[0-9a-f]{24}$/;
const PHASE_ID = /^ph_[0-9]{3,}$/;

function requireLocator(locator: PersonStateLocator): PersonStateLocator {
  if (!isPersonStateLocator(locator)) {
    throw new PersonStateApiError(400, "invalid_locator", "阅读人物位置无效");
  }
  return locator;
}

function requireCatalog(catalog: string | null | undefined): string | null {
  if (catalog === null || catalog === undefined || catalog === "") return null;
  if (!SHA256.test(catalog)) {
    throw new PersonStateApiError(400, "invalid_catalog", "catalog 必须是 sha256 摘要");
  }
  return catalog;
}

function requirePersonId(personId: string): string {
  if (typeof personId !== "string" || !PERSON_ID.test(personId)) {
    throw new PersonStateApiError(400, "invalid_person", "person_id 必须是安全的路径标识");
  }
  return personId;
}

function requirePhaseId(phaseId: string | null | undefined): string | null {
  if (phaseId === null || phaseId === undefined || phaseId === "") return null;
  if (!PHASE_ID.test(phaseId)) {
    throw new PersonStateApiError(400, "invalid_phase", "phase_id 必须是 ph_<digits>");
  }
  return phaseId;
}

function requireItemId(itemId: string): string {
  if (typeof itemId !== "string" || !ITEM_ID.test(itemId)) {
    throw new PersonStateApiError(400, "invalid_item", "item_id 必须是 psi_<24 hex>");
  }
  return itemId;
}

function requireLimit(limit: number | undefined, fallback: number): number {
  const value = limit ?? fallback;
  if (!Number.isInteger(value) || value < PERSON_STATE_LIMITS.pageMinLimit || value > PERSON_STATE_LIMITS.pageMaxLimit) {
    throw new PersonStateApiError(
      400,
      "invalid_limit",
      `limit 必须在 ${PERSON_STATE_LIMITS.pageMinLimit}..${PERSON_STATE_LIMITS.pageMaxLimit}`,
    );
  }
  return value;
}

function personStatesPrefix(locator: PersonStateLocator, personId: string): string {
  return `${PERSON_STATE_API_PREFIX}/reading-streams/${encodeURIComponent(
    locator.stream_id,
  )}/units/${encodeURIComponent(locator.unit_id)}/people/${encodeURIComponent(personId)}`;
}

// ---------------------------------------------------------------------------
// Path construction
// ---------------------------------------------------------------------------

export interface ReadingPeopleQuery {
  readonly catalog?: string | null;
  readonly limit?: number;
  readonly cursor?: string | null;
}

export interface ReadingPersonStatesQuery {
  readonly catalog?: string | null;
  readonly section?: "identities" | "changes";
  readonly phaseId?: string | null;
  readonly limit?: number;
  readonly cursor?: string | null;
}

export interface ReadingPersonStateEvidenceQuery {
  readonly catalog?: string | null;
  readonly itemId: string;
  readonly phaseId?: string | null;
  readonly limit?: number;
  readonly cursor?: string | null;
}

export function readingPeoplePath(
  locator: PersonStateLocator,
  query: ReadingPeopleQuery = {},
): string {
  const valid = requireLocator(locator);
  const params = new URLSearchParams();
  const catalog = requireCatalog(query.catalog);
  if (catalog) params.set("catalog", catalog);
  params.set("limit", String(requireLimit(query.limit, 6)));
  if (query.cursor) params.set("cursor", query.cursor);
  return `${PERSON_STATE_API_PREFIX}/reading-streams/${encodeURIComponent(
    valid.stream_id,
  )}/units/${encodeURIComponent(valid.unit_id)}/people?${params.toString()}`;
}

export function readingPersonStatesPath(
  locator: PersonStateLocator,
  personId: string,
  query: ReadingPersonStatesQuery = {},
): string {
  const valid = requireLocator(locator);
  const section = query.section ?? "identities";
  if (section !== "identities" && section !== "changes") {
    throw new PersonStateApiError(400, "invalid_section", "section 必须是 identities|changes");
  }
  const params = new URLSearchParams();
  const catalog = requireCatalog(query.catalog);
  if (catalog) params.set("catalog", catalog);
  params.set("section", section);
  const phase = requirePhaseId(query.phaseId);
  if (phase) params.set("phase_id", phase);
  params.set("limit", String(requireLimit(query.limit, 20)));
  if (query.cursor) params.set("cursor", query.cursor);
  return `${personStatesPrefix(valid, requirePersonId(personId))}/states?${params.toString()}`;
}

export function readingPersonStateEvidencePath(
  locator: PersonStateLocator,
  personId: string,
  query: ReadingPersonStateEvidenceQuery,
): string {
  const valid = requireLocator(locator);
  const params = new URLSearchParams();
  const catalog = requireCatalog(query.catalog);
  if (catalog) params.set("catalog", catalog);
  params.set("section", "evidence");
  params.set("item_id", requireItemId(query.itemId));
  const phase = requirePhaseId(query.phaseId);
  if (phase) params.set("phase_id", phase);
  params.set("limit", String(requireLimit(query.limit, 20)));
  if (query.cursor) params.set("cursor", query.cursor);
  return `${personStatesPrefix(valid, requirePersonId(personId))}/states?${params.toString()}`;
}

// ---------------------------------------------------------------------------
// Query keys: snapshot + person + section + cursor are the page identity
// ---------------------------------------------------------------------------

export const personStateKeys = {
  people: (locator: PersonStateLocator, query: ReadingPeopleQuery = {}) => {
    const valid = requireLocator(locator);
    return [
      "chronicle",
      "person-state",
      "people",
      valid.stream_id,
      valid.catalog_sha,
      valid.unit_id,
      requireLimit(query.limit, 6),
      query.cursor ?? null,
    ] as const;
  },
  states: (
    locator: PersonStateLocator,
    personId: string,
    query: ReadingPersonStatesQuery = {},
  ) => {
    const valid = requireLocator(locator);
    return [
      "chronicle",
      "person-state",
      "states",
      valid.stream_id,
      valid.catalog_sha,
      valid.unit_id,
      requirePersonId(personId),
      query.section ?? "identities",
      requirePhaseId(query.phaseId),
      requireLimit(query.limit, 20),
      query.cursor ?? null,
    ] as const;
  },
  evidence: (
    locator: PersonStateLocator,
    personId: string,
    query: ReadingPersonStateEvidenceQuery,
  ) => {
    const valid = requireLocator(locator);
    return [
      "chronicle",
      "person-state",
      "evidence",
      valid.stream_id,
      valid.catalog_sha,
      valid.unit_id,
      requirePersonId(personId),
      requireItemId(query.itemId),
      requirePhaseId(query.phaseId),
      requireLimit(query.limit, 20),
      query.cursor ?? null,
    ] as const;
  },
};

// ---------------------------------------------------------------------------
// fetch: explicit network / non-JSON / abort / typed-error branches
// ---------------------------------------------------------------------------

async function readErrorPayload(response: Response): Promise<{ code?: string; message?: string }> {
  try {
    const payload = (await response.json()) as { error?: { code?: string; message?: string } };
    return { code: payload?.error?.code, message: payload?.error?.message };
  } catch {
    return {};
  }
}

export async function fetchPersonStateJSON<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      ...init,
    });
  } catch (error) {
    if (init?.signal?.aborted) throw new PersonStateAbortError();
    throw new PersonStateApiError(0, "network_error", `无法连接人物状态服务：${path}`);
  }
  if (init?.signal?.aborted) throw new PersonStateAbortError();
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new PersonStateApiError(
      response.status,
      payload.code ?? (response.status === 404 ? "not_found" : "request_failed"),
      payload.message ?? `人物状态服务返回 HTTP ${response.status}`,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new PersonStateApiError(response.status, "invalid_response", "人物状态服务返回了无法解析的响应");
  }
}

function sameLocator(locator: PersonStateLocator, page: { stream_id?: unknown; unit_id?: unknown; catalog_sha?: unknown }): boolean {
  return (
    page?.stream_id === locator.stream_id &&
    page?.unit_id === locator.unit_id &&
    page?.catalog_sha === locator.catalog_sha
  );
}

export async function getReadingPeople(
  locator: PersonStateLocator,
  query: ReadingPeopleQuery = {},
  init?: RequestInit,
): Promise<UnitPeoplePage> {
  const valid = requireLocator(locator);
  const page = await fetchPersonStateJSON<UnitPeoplePage>(readingPeoplePath(valid, query), init);
  if (!sameLocator(valid, page)) {
    throw new PersonStateApiError(200, "inconsistent", "人物摘要与本段阅读位置不一致");
  }
  return page;
}

export async function getPersonStates(
  locator: PersonStateLocator,
  personId: string,
  query: ReadingPersonStatesQuery = {},
  init?: RequestInit,
): Promise<PersonStatePage> {
  const valid = requireLocator(locator);
  const id = requirePersonId(personId);
  const page = await fetchPersonStateJSON<PersonStatePage>(
    readingPersonStatesPath(valid, id, query),
    init,
  );
  if (!sameLocator(valid, page) || page.person_id !== id) {
    throw new PersonStateApiError(200, "inconsistent", "人物状态与本段阅读位置不一致");
  }
  return page;
}

export async function getPersonStateEvidence(
  locator: PersonStateLocator,
  personId: string,
  query: ReadingPersonStateEvidenceQuery,
  init?: RequestInit,
): Promise<StateEvidencePage> {
  const valid = requireLocator(locator);
  const id = requirePersonId(personId);
  const page = await fetchPersonStateJSON<StateEvidencePage>(
    readingPersonStateEvidencePath(valid, id, query),
    init,
  );
  if (
    !sameLocator(valid, page) ||
    page.item_id !== requireItemId(query.itemId) ||
    page.section !== "evidence"
  ) {
    throw new PersonStateApiError(200, "inconsistent", "阶段依据与本项状态不一致");
  }
  return page;
}

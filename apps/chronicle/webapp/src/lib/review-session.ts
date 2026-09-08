// Continuous-review session state for C2-R1-T11.
//
// Contract owner: apps/chronicle/docs/review-workflow.md §§2–3/5.
// This module is intentionally UI-framework free: URL scope handling,
// per-tab sessionStorage persistence (list position, open cursor, skipped
// set, isolated drafts) and the queue-advance helpers are pure and covered
// by tests/review-session.test.ts. React pages only wire these helpers to
// the T09 keyset API (listReviewPage) and the decision endpoint.
//
// Key rules encoded here:
// - URL carries status/job_id/link_kind/current review only. Cursors and
//   scroll anchors stay in sessionStorage so back/forward/refresh restore
//   the same scope and list position without leaking cursors across scopes.
// - Drafts are keyed by (review_id, plan_fingerprint). A fingerprint change
//   invalidates the old draft instead of applying it to the new plan.
// - "暂时跳过" only touches the navigation-time skipped set; it never
//   POSTs a decision and never writes dismissed/uncertain.
// - Only a successful POST clears the draft of the review it was submitted
//   for (late responses clear their original review id, never the current
//   form). Every 400/409/503, offline or unknown outcome retains the draft.

import type { ReviewLinkKind, ReviewStatus } from "./studio-api";

export type ReviewScopeStatus = ReviewStatus | "all";

export interface ReviewScope {
  status: ReviewScopeStatus;
  jobId: string | null;
  linkKind: ReviewLinkKind | null;
}

export interface ReviewScopeWithCurrent extends ReviewScope {
  currentId: string | null;
}

export const DEFAULT_REVIEW_SCOPE: ReviewScope = {
  status: "open",
  jobId: null,
  linkKind: null,
};

export const ENTITY_DECISIONS = ["same_entity", "not_same", "uncertain"] as const;
export const EVENT_DECISIONS = [
  "same_occurrence",
  "related_occurrence",
  "not_same",
  "uncertain",
] as const;

const VALID_STATUSES: ReadonlySet<string> = new Set([
  "open",
  "resolved",
  "dismissed",
  "all",
]);
const VALID_LINK_KINDS: ReadonlySet<string> = new Set(["entity", "event"]);

function cleanParam(value: string | null): string | null {
  if (value == null) return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/** Parse `?status=&job_id=&link_kind=&current=` into a scope. */
export function parseReviewSearch(search: string): ReviewScopeWithCurrent {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const rawStatus = cleanParam(params.get("status"));
  const rawKind = cleanParam(params.get("link_kind"));
  return {
    status: rawStatus && VALID_STATUSES.has(rawStatus)
      ? (rawStatus as ReviewScopeStatus)
      : "open",
    jobId: cleanParam(params.get("job_id")),
    linkKind: rawKind && VALID_LINK_KINDS.has(rawKind)
      ? (rawKind as ReviewLinkKind)
      : null,
    currentId: cleanParam(params.get("current")),
  };
}

/** Serialize a scope (+ optional current review) back to a query string. */
export function buildReviewSearch(scope: ReviewScope, currentId?: string | null): string {
  const params = new URLSearchParams();
  params.set("status", scope.status);
  if (scope.jobId) params.set("job_id", scope.jobId);
  if (scope.linkKind) params.set("link_kind", scope.linkKind);
  const current = cleanParam(currentId ?? null);
  if (current) params.set("current", current);
  return `?${params.toString()}`;
}

/**
 * Stable storage key for one list scope. The open-traversal cursor and the
 * all/resolved list position are stored separately (see ReviewSessionStore)
 * so a return position can never be reused as a status=open cursor.
 */
export function scopeKey(scope: ReviewScope): string {
  return `${scope.status}|${scope.jobId ?? "-"}|${scope.linkKind ?? "-"}`;
}

/** Draft identity: an immutable plan change must not inherit the old draft. */
export function draftKey(reviewId: string, planFingerprint: string | null | undefined): string {
  return `${reviewId}|${planFingerprint ?? "-"}`;
}

export function isDecisionAllowed(
  decision: string | null | undefined,
  allowed: ReadonlyArray<string>,
): boolean {
  if (!decision) return false;
  return allowed.includes(decision);
}

export interface GroupOverrideDraft {
  enabled: boolean;
  decision: string;
  rationale: string;
  confidence: string;
}

/**
 * Drop group overrides whose decision is no longer legal (e.g. an entity
 * decision carried onto an event review). Legal overrides are preserved so a
 * 409 conflict never loses the reviewer's per-group work.
 */
export function sanitizeGroupOverrides(
  overrides: Record<string, GroupOverrideDraft>,
  allowed: ReadonlyArray<string>,
): Record<string, GroupOverrideDraft> {
  const kept: Record<string, GroupOverrideDraft> = {};
  for (const [groupId, draft] of Object.entries(overrides)) {
    if (!draft.enabled) {
      kept[groupId] = draft;
      continue;
    }
    if (draft.decision && allowed.includes(draft.decision)) {
      kept[groupId] = draft;
    }
  }
  return kept;
}

/**
 * When the allowed vocabulary changes (Entity→Event navigation or a fresh
 * detail load), an illegal carried-over decision resets to the first legal
 * one instead of being submitted against the wrong kind.
 */
export function sanitizeDecision(
  decision: string | null | undefined,
  allowed: ReadonlyArray<string>,
): string {
  if (decision && allowed.includes(decision)) return decision;
  return allowed.length ? allowed[0] : "";
}

export interface ReviewDraftState {
  decision: string;
  rationale: string;
  confidence: string;
  showExceptions: boolean;
  groupOverrides: Record<string, GroupOverrideDraft>;
  updatedAt: string;
}

export interface ListPosition {
  cursor: string | null;
  anchorId: string | null;
}

export type MinimalStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function memoryStorage(): MinimalStorage {
  const cells = new Map<string, string>();
  return {
    getItem: (key: string) => (cells.has(key) ? cells.get(key) as string : null),
    setItem: (key: string, value: string) => {
      cells.set(key, value);
    },
    removeItem: (key: string) => {
      cells.delete(key);
    },
  };
}

const NAMESPACE = "chronicle.review-session.v1";

/**
 * Per-tab persistence. One instance wraps sessionStorage; tests inject
 * memoryStorage(). Every key is namespaced by scope so changing the scope
 * clears pagination state without moving another item's draft onto the
 * current form.
 */
export class ReviewSessionStore {
  private readonly storage: MinimalStorage;

  constructor(storage: MinimalStorage) {
    this.storage = storage;
  }

  private readJson(key: string): unknown {
    try {
      const raw = this.storage.getItem(`${NAMESPACE}.${key}`);
      if (!raw) return null;
      return JSON.parse(raw) as unknown;
    } catch {
      return null;
    }
  }

  private writeJson(key: string, value: unknown): void {
    try {
      this.storage.setItem(`${NAMESPACE}.${key}`, JSON.stringify(value));
    } catch {
      // Persistence is best-effort; the in-memory React state above still
      // guards the current page lifetime.
    }
  }

  loadDraft(reviewId: string, planFingerprint: string | null | undefined): ReviewDraftState | null {
    const parsed = this.readJson(`draft.${draftKey(reviewId, planFingerprint)}`);
    if (!parsed || typeof parsed !== "object") return null;
    const record = parsed as Partial<ReviewDraftState>;
    if (typeof record.decision !== "string") return null;
    return {
      decision: record.decision,
      rationale: typeof record.rationale === "string" ? record.rationale : "",
      confidence: typeof record.confidence === "string" ? record.confidence : "0.5",
      showExceptions: record.showExceptions === true,
      groupOverrides:
        record.groupOverrides && typeof record.groupOverrides === "object"
          ? (record.groupOverrides as Record<string, GroupOverrideDraft>)
          : {},
      updatedAt: typeof record.updatedAt === "string" ? record.updatedAt : "",
    };
  }

  saveDraft(
    reviewId: string,
    planFingerprint: string | null | undefined,
    draft: Omit<ReviewDraftState, "updatedAt">,
  ): void {
    this.writeJson(`draft.${draftKey(reviewId, planFingerprint)}`, {
      ...draft,
      updatedAt: new Date().toISOString(),
    });
  }

  clearDraft(reviewId: string, planFingerprint: string | null | undefined): void {
    try {
      this.storage.removeItem(`${NAMESPACE}.draft.${draftKey(reviewId, planFingerprint)}`);
    } catch {
      // Best-effort; the caller already advanced away from this draft.
    }
  }

  loadSkipped(scope: ReviewScope): string[] {
    const parsed = this.readJson(`skipped.${scopeKey(scope)}`);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === "string" && id.length > 0);
  }

  addSkipped(scope: ReviewScope, reviewId: string): string[] {
    const next = [...new Set([...this.loadSkipped(scope), reviewId])];
    this.writeJson(`skipped.${scopeKey(scope)}`, next);
    return next;
  }

  clearSkipped(scope: ReviewScope): void {
    try {
      this.storage.removeItem(`${NAMESPACE}.skipped.${scopeKey(scope)}`);
    } catch {
      // Best-effort.
    }
  }

  loadListPosition(scope: ReviewScope): ListPosition | null {
    const parsed = this.readJson(`position.${scopeKey(scope)}`);
    if (!parsed || typeof parsed !== "object") return null;
    const record = parsed as Partial<ListPosition>;
    return {
      cursor: typeof record.cursor === "string" ? record.cursor : null,
      anchorId: typeof record.anchorId === "string" ? record.anchorId : null,
    };
  }

  saveListPosition(scope: ReviewScope, position: ListPosition): void {
    this.writeJson(`position.${scopeKey(scope)}`, position);
  }

  /** Open-traversal cursor, stored independently from list return state. */
  loadOpenCursor(scope: ReviewScope): string | null {
    const parsed = this.readJson(`open-cursor.${scopeKey(scope)}`);
    return typeof parsed === "string" ? parsed : null;
  }

  saveOpenCursor(scope: ReviewScope, cursor: string | null): void {
    this.writeJson(`open-cursor.${scopeKey(scope)}`, cursor);
  }
}

/**
 * Next open id strictly after currentId in traversal order, skipping the
 * navigation-time skipped set. Returns null when the current page/round has
 * no further candidate (the caller then runs the tail re-scan from the head
 * of the scope, which also picks up rows inserted before the old cursor).
 */
export function findNextOpenId(
  orderedOpenIds: string[],
  currentId: string | null,
  skipped: ReadonlySet<string>,
): string | null {
  const start = currentId ? orderedOpenIds.indexOf(currentId) + 1 : 0;
  for (let index = Math.max(start, 0); index < orderedOpenIds.length; index += 1) {
    const id = orderedOpenIds[index];
    if (id === currentId || skipped.has(id)) continue;
    return id;
  }
  return null;
}

export type TailRescanOutcome =
  | { kind: "next"; nextId: string; stillOpenSkipped: number }
  | { kind: "only-skipped"; nextId: null; stillOpenSkipped: number }
  | { kind: "empty"; nextId: null; stillOpenSkipped: 0 };

/**
 * End-of-round evaluation over a full head-to-tail re-scan. stillOpenSkipped
 * counts skipped ids that are still open (already-handled items are never
 * counted), never the local set size.
 */
export function evaluateTailRescan(
  allOpenIdsInOrder: string[],
  skipped: ReadonlySet<string>,
): TailRescanOutcome {
  const open = new Set(allOpenIdsInOrder);
  const stillOpenSkipped = countStillOpenSkipped([...skipped], open);
  const nextId = allOpenIdsInOrder.find((id) => !skipped.has(id)) ?? null;
  if (nextId) return { kind: "next", nextId, stillOpenSkipped };
  if (stillOpenSkipped > 0) return { kind: "only-skipped", nextId: null, stillOpenSkipped };
  return { kind: "empty", nextId: null, stillOpenSkipped: 0 };
}

/** Local skipped ids ∩ server-open ids; handled-elsewhere items drop out. */
export function countStillOpenSkipped(
  skippedIds: ReadonlyArray<string>,
  openIds: ReadonlySet<string>,
): number {
  let count = 0;
  for (const id of new Set(skippedIds)) {
    if (openIds.has(id)) count += 1;
  }
  return count;
}

import { describe, expect, it } from "vitest";
import {
  buildReviewSearch,
  countStillOpenSkipped,
  draftKey,
  evaluateTailRescan,
  findNextOpenId,
  memoryStorage,
  parseReviewSearch,
  ReviewSessionStore,
  sanitizeDecision,
  sanitizeGroupOverrides,
  scopeKey,
} from "../src/lib/review-session";

describe("review scope URL round-trip", () => {
  it("keeps status/job/kind/current in the URL and defaults safely", () => {
    expect(parseReviewSearch("")).toEqual({
      status: "open",
      jobId: null,
      linkKind: null,
      currentId: null,
    });
    const scope = parseReviewSearch("?status=open&job_id=job-1&link_kind=entity&current=r-9");
    expect(scope).toEqual({ status: "open", jobId: "job-1", linkKind: "entity", currentId: "r-9" });
    expect(parseReviewSearch(buildReviewSearch(scope, scope.currentId))).toEqual(scope);
  });

  it("rejects unknown status/kind instead of carrying them into the scope", () => {
    expect(parseReviewSearch("?status=bogus&link_kind=bogus")).toMatchObject({
      status: "open",
      linkKind: null,
    });
  });

  it("isolates storage namespaces per scope", () => {
    const a = scopeKey({ status: "open", jobId: "job-1", linkKind: null });
    const b = scopeKey({ status: "open", jobId: "job-2", linkKind: null });
    const c = scopeKey({ status: "resolved", jobId: "job-1", linkKind: null });
    expect(new Set([a, b, c]).size).toBe(3);
  });
});

describe("draft isolation", () => {
  it("keys drafts by (review_id, plan_fingerprint)", () => {
    expect(draftKey("r1", "fp-a")).not.toBe(draftKey("r1", "fp-b"));
    expect(draftKey("r1", "fp-a")).not.toBe(draftKey("r2", "fp-a"));
  });

  it("never applies an entity decision to an event review", () => {
    expect(sanitizeDecision("same_entity", ["same_occurrence", "related_occurrence", "not_same", "uncertain"])).toBe(
      "same_occurrence",
    );
    expect(sanitizeDecision("uncertain", ["same_entity", "not_same", "uncertain"])).toBe("uncertain");
    expect(sanitizeDecision("", ["same_entity", "not_same", "uncertain"])).toBe("same_entity");
  });

  it("drops illegal group overrides but keeps legal per-group work", () => {
    const kept = sanitizeGroupOverrides(
      {
        legal: { enabled: true, decision: "not_same", rationale: "x", confidence: "0.9" },
        illegal: { enabled: true, decision: "same_entity", rationale: "y", confidence: "0.9" },
        idle: { enabled: false, decision: "same_entity", rationale: "", confidence: "0.5" },
      },
      ["same_occurrence", "related_occurrence", "not_same", "uncertain"],
    );
    expect(Object.keys(kept).sort()).toEqual(["idle", "legal"]);
  });

  it("round-trips one draft per (review, fingerprint) and clears only it", () => {
    const store = new ReviewSessionStore(memoryStorage());
    store.saveDraft("r1", "fp-a", {
      decision: "same_entity",
      rationale: "核对证据",
      confidence: "0.9",
      showExceptions: true,
      groupOverrides: {},
    });
    expect(store.loadDraft("r1", "fp-a")?.rationale).toBe("核对证据");
    // A rotated plan must not inherit the old draft.
    expect(store.loadDraft("r1", "fp-b")).toBeNull();
    // Another review must not inherit it either.
    expect(store.loadDraft("r2", "fp-a")).toBeNull();
    store.clearDraft("r1", "fp-a");
    expect(store.loadDraft("r1", "fp-a")).toBeNull();
  });
});

describe("skipped set and list position", () => {
  it("keeps skips navigation-local and scoped", () => {
    const store = new ReviewSessionStore(memoryStorage());
    const scopeA = { status: "open" as const, jobId: "job-1", linkKind: null };
    const scopeB = { status: "open" as const, jobId: null, linkKind: null };
    store.addSkipped(scopeA, "r1");
    store.addSkipped(scopeA, "r1");
    expect(store.loadSkipped(scopeA)).toEqual(["r1"]);
    expect(store.loadSkipped(scopeB)).toEqual([]);
  });

  it("stores the list position and the open cursor independently", () => {
    const store = new ReviewSessionStore(memoryStorage());
    const scope = { status: "open" as const, jobId: null, linkKind: null };
    store.saveListPosition(scope, { cursor: "cursor-3", anchorId: "r-30" });
    store.saveOpenCursor(scope, "cursor-9");
    expect(store.loadListPosition(scope)).toEqual({ cursor: "cursor-3", anchorId: "r-30" });
    expect(store.loadOpenCursor(scope)).toBe("cursor-9");
  });
});

describe("continuous traversal", () => {
  it("advances past the current item and avoids skipped ids", () => {
    expect(findNextOpenId(["r1", "r2", "r3"], "r1", new Set())).toBe("r2");
    expect(findNextOpenId(["r1", "r2", "r3"], "r1", new Set(["r2"]))).toBe("r3");
    expect(findNextOpenId(["r1", "r2", "r3"], "r3", new Set())).toBeNull();
    expect(findNextOpenId(["r1"], null, new Set(["r1"]))).toBeNull();
  });

  it("finds late rows on a head re-scan and reports only-skipped vs empty", () => {
    // A row inserted before the old cursor appears at the head again.
    expect(evaluateTailRescan(["r0", "r2"], new Set(["r9"]))).toEqual({
      kind: "next",
      nextId: "r0",
      stillOpenSkipped: 0,
    });
    // Skipped items handled by another tab are not counted.
    expect(evaluateTailRescan(["r2"], new Set(["r1", "r2"]))).toEqual({
      kind: "only-skipped",
      nextId: null,
      stillOpenSkipped: 1,
    });
    expect(evaluateTailRescan([], new Set(["r1"]))).toEqual({
      kind: "empty",
      nextId: null,
      stillOpenSkipped: 0,
    });
  });

  it("never counts handled-elsewhere skips toward the remaining total", () => {
    expect(countStillOpenSkipped(["r1", "r2", "r2"], new Set(["r2", "r3"]))).toBe(1);
    expect(countStillOpenSkipped([], new Set(["r1"]))).toBe(0);
  });
});

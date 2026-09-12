import { describe, expect, it } from "vitest";
import {
  buildReviewSearch,
  compareReviewSortKey,
  countStillOpenSkipped,
  draftKey,
  evaluateTailRescan,
  findNextAfterAnchor,
  findNextOpenId,
  memoryStorage,
  parseReviewSearch,
  ReviewSessionStore,
  sanitizeDecision,
  sanitizeGroupOverrides,
  scopeKey,
} from "../src/lib/review-session";

describe("review scope URL round-trip", () => {
  it("keeps status/job/kind/scope/current in the URL and defaults safely", () => {
    expect(parseReviewSearch("")).toEqual({
      status: "open",
      jobId: null,
      linkKind: null,
      reviewScope: "all",
      currentId: null,
    });
    const scope = parseReviewSearch("?status=open&job_id=job-1&link_kind=entity&review_scope=resolution&current=r-9");
    expect(scope).toEqual({
      status: "open",
      jobId: "job-1",
      linkKind: "entity",
      reviewScope: "resolution",
      currentId: "r-9",
    });
    expect(parseReviewSearch(buildReviewSearch(scope, scope.currentId))).toEqual(scope);
  });

  it("drops link_kind outside the resolution family", () => {
    expect(parseReviewSearch("?review_scope=all&link_kind=entity").linkKind).toBeNull();
    expect(parseReviewSearch("?review_scope=person_state&link_kind=event").linkKind).toBeNull();
    expect(parseReviewSearch("?review_scope=bogus").reviewScope).toBe("all");
  });

  it("rejects unknown status/kind instead of carrying them into the scope", () => {
    expect(parseReviewSearch("?status=bogus&link_kind=bogus")).toMatchObject({
      status: "open",
      linkKind: null,
    });
  });

  it("isolates storage namespaces per scope, including the queue family", () => {
    const a = scopeKey({ status: "open", jobId: "job-1", linkKind: null, reviewScope: "all" });
    const b = scopeKey({ status: "open", jobId: "job-2", linkKind: null, reviewScope: "all" });
    const c = scopeKey({ status: "resolved", jobId: "job-1", linkKind: null, reviewScope: "all" });
    const d = scopeKey({ status: "open", jobId: "job-1", linkKind: null, reviewScope: "person_state" });
    expect(new Set([a, b, c, d]).size).toBe(4);
  });
});

describe("draft isolation", () => {
  it("keys drafts by (review_id, plan_fingerprint, review_scope)", () => {
    expect(draftKey("r1", "fp-a")).not.toBe(draftKey("r1", "fp-b"));
    expect(draftKey("r1", "fp-a")).not.toBe(draftKey("r2", "fp-a"));
    expect(draftKey("r1", "fp-a", "person_state")).not.toBe(draftKey("r1", "fp-a", "resolution"));
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

describe("stable sort-anchor traversal (deep-page regression)", () => {
  function deepQueue(size: number) {
    // 450-item queue sharing a few created_at values, in server order.
    const ordered: Array<{ reviewId: string; createdAt: string }> = [];
    for (let i = 0; i < size; i += 1) {
      ordered.push({
        reviewId: `r-${String(i).padStart(4, "0")}`,
        createdAt: `2026-09-0${1 + (i % 7)}T00:00:00+00:00`,
      });
    }
    return ordered.sort(
      (a, b) =>
        compareReviewSortKey(
          { createdAt: a.createdAt, reviewId: a.reviewId },
          { createdAt: b.createdAt, reviewId: b.reviewId },
        ),
    );
  }

  it("continues after a deep-page item that left the open queue", () => {
    const queue = deepQueue(450);
    const deepIndex = 320;
    const anchor = {
      createdAt: queue[deepIndex].createdAt,
      reviewId: queue[deepIndex].reviewId,
    };
    // Successful POST removed the current review from the open list.
    const afterSubmit = queue.filter((entry) => entry.reviewId !== anchor.reviewId);
    expect(
      findNextAfterAnchor(afterSubmit, anchor, new Set()),
    ).toBe(queue[deepIndex + 1].reviewId);
  });

  it("does not fall back to the head when the anchor id is absent", () => {
    const queue = deepQueue(450);
    const anchor = {
      createdAt: queue[200].createdAt,
      reviewId: queue[200].reviewId,
    };
    const afterSubmit = queue.filter((entry) => entry.reviewId !== anchor.reviewId);
    expect(findNextAfterAnchor(afterSubmit, anchor, new Set())).not.toBe(queue[0].reviewId);
  });

  it("orders equal created_at by review_id and nulls last like Postgres", () => {
    expect(
      compareReviewSortKey(
        { createdAt: "2026-09-01T00:00:00+00:00", reviewId: "r-b" },
        { createdAt: "2026-09-01T00:00:00+00:00", reviewId: "r-a" },
      ),
    ).toBeGreaterThan(0);
    expect(
      compareReviewSortKey(
        { createdAt: null, reviewId: "r-a" },
        { createdAt: "2026-09-01T00:00:00+00:00", reviewId: "r-z" },
      ),
    ).toBeGreaterThan(0);
  });

  it("respects the skipped set and restarts from the head on a null anchor", () => {
    const ordered = [
      { reviewId: "r-1", createdAt: "2026-09-01T00:00:00+00:00" },
      { reviewId: "r-2", createdAt: "2026-09-02T00:00:00+00:00" },
    ];
    const anchor = { createdAt: "2026-09-01T00:00:00+00:00", reviewId: "r-1" };
    expect(findNextAfterAnchor(ordered, anchor, new Set(["r-2"]))).toBeNull();
    expect(findNextAfterAnchor(ordered, null, new Set(["r-1"]))).toBe("r-2");
    // A still-open current review is never selected via its own anchor.
    expect(findNextAfterAnchor(ordered, anchor, new Set())).toBe("r-2");
  });
});

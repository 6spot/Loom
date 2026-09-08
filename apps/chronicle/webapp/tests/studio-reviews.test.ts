import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getReview,
  listReviewPage,
  listReviews,
  StudioApiError,
  submitReviewDecision,
} from "../src/lib/studio-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubReviewFetch(calls: Array<{ path: string; init?: RequestInit }>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init });
      expect(new Headers(init?.headers).get("Authorization")).toBe("Basic abc");
      expect(init?.credentials).toBe("same-origin");
      if (path.includes("/decision")) {
        return new Response(
          JSON.stringify({
            schema: "chronicle.review",
            version: "0.1",
            review: { review_id: "r1", status: "resolved" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (path.endsWith("/r1")) {
        return new Response(
          JSON.stringify({
            schema: "chronicle.review",
            version: "0.1",
            review: { review_id: "r1", status: "open" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify({
          schema: "chronicle.studio-review-page",
          version: "0.2",
          query: { status: "open", job_id: null, link_kind: null, limit: 100 },
          items: [],
          next_cursor: null,
          open_count: 0,
          observed_at: "2026-02-01T00:00:00+00:00",
          plan_fingerprint: "f".repeat(64),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }),
  );
}

describe("Studio review API client", () => {
  it("preserves the typed 409 context and leaves a corrected decision to the reviewer", async () => {
    const details = {
      canonical_ids: ["canonical-a", "canonical-b"],
      review_group_ids: ["group-x"],
      incoming_refs: [{ bundle: "incoming", ref: "ent_x" }],
    };
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      schema: "chronicle.error", version: "0.1",
      error: { code: "canonical_identity_conflict", message: "该判断无法提交", details },
    }), { status: 409, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);

    const error = await submitReviewDecision("Basic abc", "r1", "same_entity", "核对证据", 0.9)
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(StudioApiError);
    expect(error).toMatchObject({
      status: 409, code: "canonical_identity_conflict", message: "该判断无法提交", details,
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("uses the authenticated job-scoped review subresource without changing legacy bodies", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    stubReviewFetch(calls);

    await listReviews("Basic abc", "open");
    await getReview("Basic abc", "r1");
    await submitReviewDecision(
      "Basic abc",
      "r1",
      "uncertain",
      "evidence remains insufficient",
      0.4,
    );

    expect(calls[0].path).toContain("/api/v1/studio/jobs/reviews?status=open");
    expect(calls[0].path).not.toContain("offset");
    expect(calls[1].path).toBe("/api/v1/studio/jobs/reviews/r1");
    expect(calls[2].path).toBe("/api/v1/studio/jobs/reviews/r1/decision");
    expect(calls[2].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({
      decision: "uncertain",
      rationale: "evidence remains insufficient",
      confidence: 0.4,
    });
  });

  it("reads one keyset page with scope filters and returns page metadata", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        seen.push(String(input));
        return new Response(
          JSON.stringify({
            schema: "chronicle.studio-review-page",
            version: "0.2",
            query: { status: "open", job_id: "job-1", link_kind: "entity", limit: 2 },
            items: [{ review_id: "r1" }, { review_id: "r2" }],
            next_cursor: "cursor-2",
            open_count: 3,
            observed_at: "2026-02-01T00:00:00+00:00",
            plan_fingerprint: "a".repeat(64),
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    const page = await listReviewPage("Basic abc", {
      status: "open",
      jobId: "job-1",
      linkKind: "entity",
      limit: 2,
    });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toContain("status=open");
    expect(seen[0]).toContain("job_id=job-1");
    expect(seen[0]).toContain("link_kind=entity");
    expect(seen[0]).toContain("limit=2");
    expect(seen[0]).not.toContain("offset");
    expect(page.items.map((item) => item.review_id)).toEqual(["r1", "r2"]);
    expect(page.next_cursor).toBe("cursor-2");
    expect(page.open_count).toBe(3);
    expect(page.plan_fingerprint).toBe("a".repeat(64));
  });

  it("traverses every keyset page for legacy full-list readers", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        seen.push(path);
        const last = path.includes("cursor=");
        return new Response(
          JSON.stringify({
            schema: "chronicle.studio-review-page",
            version: "0.2",
            query: { status: "open", job_id: null, link_kind: null, limit: 100 },
            items: last ? [{ review_id: "r2" }] : [{ review_id: "r1" }],
            next_cursor: last ? null : "cursor-1",
            open_count: 2,
            observed_at: "2026-02-01T00:00:00+00:00",
            plan_fingerprint: "b".repeat(64),
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    const all = await listReviews("Basic abc", "open");
    expect(all.map((item) => item.review_id)).toEqual(["r1", "r2"]);
    expect(seen).toHaveLength(2);
    expect(seen[1]).toContain("cursor=cursor-1");
  });

  it("sends explicit per-group overrides only when the reviewer chooses an exception", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    stubReviewFetch(calls);

    await submitReviewDecision(
      "Basic abc",
      "r1",
      "same_entity",
      "most source groups refer to the published identity",
      0.95,
      [
        {
          review_group_id: "rg_exception",
          decision: "not_same",
          confidence: 0.9,
          rationale: "this group's exact evidence identifies a different person",
        },
      ],
    );

    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      decision: "same_entity",
      rationale: "most source groups refer to the published identity",
      confidence: 0.95,
      group_decisions: [
        {
          review_group_id: "rg_exception",
          decision: "not_same",
          confidence: 0.9,
          rationale: "this group's exact evidence identifies a different person",
        },
      ],
    });
  });
});

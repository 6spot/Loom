import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getReview,
  listReviews,
  submitReviewDecision,
} from "../src/lib/studio-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Studio review API client", () => {
  it("uses the authenticated job-scoped review subresource", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        calls.push({ path, init });
        expect(new Headers(init?.headers).get("Authorization")).toBe("Basic abc");
        expect(init?.credentials).toBe("same-origin");
        if (path.includes("/decision")) {
          return new Response(JSON.stringify({ schema: "chronicle.review", version: "0.1", review: { review_id: "r1", status: "resolved" } }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (path.endsWith("/r1")) {
          return new Response(JSON.stringify({ schema: "chronicle.review", version: "0.1", review: { review_id: "r1", status: "open" } }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        return new Response(JSON.stringify({ schema: "chronicle.review-list", version: "0.1", reviews: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );

    await listReviews("Basic abc", "open");
    await getReview("Basic abc", "r1");
    await submitReviewDecision("Basic abc", "r1", "uncertain", "evidence remains insufficient", 0.4);

    expect(calls[0].path).toContain("/api/v1/studio/jobs/reviews?status=open");
    expect(calls[1].path).toBe("/api/v1/studio/jobs/reviews/r1");
    expect(calls[2].path).toBe("/api/v1/studio/jobs/reviews/r1/decision");
    expect(calls[2].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[2].init?.body))).toEqual({
      decision: "uncertain",
      rationale: "evidence remains insufficient",
      confidence: 0.4,
    });
  });
});

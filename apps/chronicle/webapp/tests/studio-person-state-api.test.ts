// C2-R3-T10 Studio person-state review client 单元测试。
//
// 覆盖 person-state-reading.md §5.1 的 typed client 合同：
// - 混合队列通过 review_scope 选择范围；省略保持 resolution（仍含 narrative
//   facts/prose），`all` 覆盖 resolution/person_state/narrative，且不会把
//   narrative 结果丢掉；
// - link_kind 只属于 resolution，和 person_state/all 混用与后端一样是 400；
// - 状态评估提交 payload 固定为
//   `{plan_fingerprint, default_assessment, overrides, rationale}`，不会串成
//   resolution/narrative 的 decision/confidence payload；
// - 错 scope / plan 漂移的 409 原样抛出，不吞错、不改写。全部为合成数据。

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  listReviewPage,
  StudioApiError,
  submitPersonStateAssessment,
  submitReviewDecision,
} from "../src/lib/studio-api";
import type { AssessmentOverlay } from "../src/lib/person-state-types";

const PLAN = "f".repeat(64);
const REVIEW_ID = "01a08e83-d302-7d83-8d0b-6e163ee27737";

const OVERLAY: AssessmentOverlay = {
  plan_fingerprint: PLAN,
  default_assessment: "supported",
  overrides: [{ candidate_key: "cand-1", assessment: "uncertain", rationale: "证据不足" }],
  rationale: "整章阶段依据复核",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function reviewPage(overrides: Record<string, unknown> = {}) {
  return {
    schema: "chronicle.studio-review-page",
    version: "0.2",
    query: { status: "open", job_id: null, link_kind: null, limit: 50 },
    items: [
      { review_id: "res-1", scope: "resolution" },
      { review_id: "nar-1", scope: "narrative", narrative_kind: "facts" },
      {
        review_id: REVIEW_ID,
        scope: "person_state",
        review_mode: "chapter_state_evidence",
        plan_fingerprint: PLAN,
        candidate_count: 3,
        default_assessment: "uncertain",
        allowed_assessments: ["supported", "uncertain", "disputed", "rejected"],
      },
    ],
    next_cursor: null,
    open_count: 3,
    observed_at: "2026-09-12T00:00:00+00:00",
    plan_fingerprint: PLAN,
    ...overrides,
  };
}

describe("Studio review queue scope selection", () => {
  it("adds review_scope=all and keeps the mixed narrative/person_state items", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        seen.push(String(input));
        return new Response(JSON.stringify(reviewPage()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const page = await listReviewPage("Basic abc", { reviewScope: "all", limit: 50 });
    expect(seen).toHaveLength(1);
    expect(seen[0]).toContain("review_scope=all");
    expect(page.items.map((item) => item.scope)).toEqual([
      "resolution",
      "narrative",
      "person_state",
    ]);
    expect(page.items[1]).toMatchObject({ narrative_kind: "facts" });
    expect(page.items[2]).toMatchObject({ review_mode: "chapter_state_evidence", candidate_count: 3 });
  });

  it("omits review_scope by default so the legacy resolution queue is unchanged", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        seen.push(String(input));
        return new Response(JSON.stringify(reviewPage()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    await listReviewPage("Basic abc", { status: "open" });
    expect(seen[0]).not.toContain("review_scope");
  });

  it("rejects link_kind mixed with person_state/all like the server does", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      listReviewPage("Basic abc", { reviewScope: "person_state", linkKind: "entity" }),
    ).rejects.toMatchObject({ status: 400, code: "invalid_scope" });
    await expect(
      listReviewPage("Basic abc", { reviewScope: "all", linkKind: "event" }),
    ).rejects.toMatchObject({ status: 400, code: "invalid_scope" });
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("submitPersonStateAssessment", () => {
  it("posts the frozen assessment payload without a resolution/narrative decision", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ path: String(input), init });
        return new Response(
          JSON.stringify({
            schema: "chronicle.review",
            version: "0.1",
            review: { review_id: REVIEW_ID, scope: "person_state", status: "resolved" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    const review = await submitPersonStateAssessment("Basic abc", REVIEW_ID, OVERLAY);
    expect(review).toMatchObject({ scope: "person_state", status: "resolved" });
    expect(calls[0].path).toBe(`/api/v1/studio/jobs/reviews/${REVIEW_ID}/decision`);
    expect(calls[0].init?.method).toBe("POST");
    const body = JSON.parse(String(calls[0].init?.body));
    expect(body).toEqual({
      plan_fingerprint: PLAN,
      default_assessment: "supported",
      overrides: [{ candidate_key: "cand-1", assessment: "uncertain", rationale: "证据不足" }],
      rationale: "整章阶段依据复核",
    });
    expect(body).not.toHaveProperty("decision");
    expect(body).not.toHaveProperty("confidence");
    expect(body).not.toHaveProperty("candidate_sha");
  });

  it("surfaces a wrong-scope or drifted 409 without swallowing it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            schema: "chronicle.error",
            version: "0.1",
            error: { code: "plan_drift", message: "frozen against a different plan" },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const error = await submitPersonStateAssessment("Basic abc", REVIEW_ID, OVERLAY).catch(
      (failure: unknown) => failure,
    );
    expect(error).toBeInstanceOf(StudioApiError);
    expect(error).toMatchObject({ status: 409, code: "plan_drift" });
  });

  it("keeps the resolution decision method separate from the state payload", async () => {
    const calls: Array<{ init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({ init });
        return new Response(
          JSON.stringify({
            schema: "chronicle.review",
            version: "0.1",
            review: { review_id: "res-1", status: "resolved" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    await submitReviewDecision("Basic abc", "res-1", "same_entity", "核对", 0.9);
    const body = JSON.parse(String(calls[0].init?.body));
    expect(body).toMatchObject({ decision: "same_entity", confidence: 0.9 });
    expect(body).not.toHaveProperty("plan_fingerprint");
    expect(body).not.toHaveProperty("default_assessment");
  });
});

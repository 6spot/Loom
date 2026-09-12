import { afterEach, describe, expect, it, vi } from "vitest";
import { buildContentDecision, contentDraftKey, contentPatches, pointerValue } from "../src/lib/chapter-content-review";
import { listReviewPage, submitChapterContentDecision, StudioApiError } from "../src/lib/studio-api";
import { parseReviewSearch } from "../src/lib/review-session";
import { contentData, readyDraft } from "./fixtures/chapter-content";

afterEach(() => vi.unstubAllGlobals());

describe("chapter content review version and patch boundaries", () => {
  it("accepts only the unchanged candidate with every issue disposition", () => {
    const data = contentData();
    const result = buildContentDecision(data, readyDraft(), "accept");
    expect(result).toMatchObject({ decision: "accept", candidate_sha256: data.candidate_sha256, history_sha256: data.history_sha256 });
    expect(result).not.toHaveProperty("patches");
    expect(result.issue_dispositions.map((item) => item.issue_id)).toEqual(["subject"]);
  });
  it("separates changing a paragraph from accepting it", () => {
    const data = contentData();
    const draft = readyDraft();
    draft.edits["/translation/blocks/0/text"] = "重新核对后的第一段。";
    expect(() => buildContentDecision(data, draft, "accept")).toThrow("原版本");
    const result = buildContentDecision(data, draft, "revise");
    expect(result.patches).toEqual([{ op: "replace", path: "/translation/blocks/0/text", before_sha256: "6".repeat(64), value: "重新核对后的第一段。" }]);
    expect(pointerValue(data.candidate, "/translation/blocks/0/text")).toBe("第一段完整译文。");
  });
  it("does not carry no-op edits or allow an unrecognized target", () => {
    const data = contentData();
    expect(contentPatches(data, { "/translation/blocks/0/text": "第一段完整译文。" })).toEqual([]);
    expect(() => contentPatches(data, { "/source_scope": "{}" })).toThrow("版本已改变");
  });
  it("keeps a failed metadata edit from blocking an explicit rejection", () => {
    const draft = readyDraft();
    draft.edits["/bundle/entities/0"] = "not valid JSON";
    expect(buildContentDecision(contentData(), draft, "reject")).not.toHaveProperty("patches");
  });
  it("rejects omitted issues and cannot relabel a processing error as source uncertainty", () => {
    const draft = readyDraft();
    draft.dispositions = {};
    expect(() => buildContentDecision(contentData(), draft, "accept")).toThrow("逐项");
    const mislabeled = readyDraft();
    mislabeled.dispositions.subject.disposition = "source_uncertainty";
    expect(() => buildContentDecision(contentData(), mislabeled, "accept")).toThrow("处理错误");
  });
  it("never accepts a partial candidate", () => {
    const data = { ...contentData(), candidate: null, candidate_sha256: null, can_accept: false };
    expect(() => buildContentDecision(data, readyDraft(), "accept")).toThrow();
    expect(buildContentDecision(data, readyDraft(), "reject").candidate_sha256).toBeNull();
  });
  it("isolates review drafts by scope and all candidate versions", () => {
    const data = contentData();
    const key = contentDraftKey("all", "review-1", data);
    expect(contentDraftKey("chapter_content", "review-1", data)).not.toBe(key);
    expect(contentDraftKey("all", "review-2", data)).not.toBe(key);
    expect(contentDraftKey("all", "review-1", { ...data, candidate_sha256: "9".repeat(64) })).not.toBe(key);
    expect(parseReviewSearch("review_scope=chapter_content&link_kind=entity")).toMatchObject({ reviewScope: "chapter_content", linkKind: null });
  });
});

describe("chapter-content typed API", () => {
  it("passes the explicit queue scope without confusing identity filters", async () => {
    const mock = vi.fn(async () => new Response(JSON.stringify({ items: [], open_count: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", mock);
    await listReviewPage("Basic fixture", { reviewScope: "chapter_content" });
    expect(String(mock.mock.calls[0]?.[0])).toContain("review_scope=chapter_content");
    await expect(listReviewPage(null, { reviewScope: "chapter_content", linkKind: "entity" })).rejects.toBeInstanceOf(StudioApiError);
    expect(mock).toHaveBeenCalledTimes(1);
  });
  it("sends fixed version hashes and preserves 409 failures", async () => {
    const payload = buildContentDecision(contentData(), readyDraft(), "accept");
    const mock = vi.fn(async (_path: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ error: { code: "plan_drift", message: "changed" } }), { status: 409 }));
    vi.stubGlobal("fetch", mock);
    await expect(submitChapterContentDecision(null, "review-1", payload)).rejects.toMatchObject({ status: 409, code: "plan_drift" });
    expect(JSON.parse(String(mock.mock.calls[0]?.[1]?.body))).toEqual(payload);
  });
});

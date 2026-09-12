// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChapterContentReviewPanel from "./ChapterContentReviewPanel";
import { buildContentDecision, contentDraftKey } from "../../lib/chapter-content-review";
import { submitChapterContentDecision } from "../../lib/studio-api";
import { contentItem, readyDraft } from "../../../tests/fixtures/chapter-content";

vi.mock("../../lib/studio-auth", () => ({ useStudioAuth: () => ({ authHeader: () => "Basic fixture" }) }));
vi.mock("./ReviewEvidencePanel", () => ({ ReviewEvidencePanel: () => <div>完整原文查看器</div> }));
vi.mock("../../lib/studio-api", async (importOriginal) => ({ ...await importOriginal<object>(), submitChapterContentDecision: vi.fn() }));

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  sessionStorage.clear();
  vi.mocked(submitChapterContentDecision).mockReset();
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

function button(text: string): HTMLButtonElement {
  const result = Array.from(container.querySelectorAll("button")).find((entry) => entry.textContent === text);
  if (!result) throw new Error(`missing button ${text}`);
  return result;
}

async function render(item = contentItem(), onNext = vi.fn(async () => {})) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter>
    <ChapterContentReviewPanel item={item} queueScope="all" onNext={onNext} onSkip={async () => {}} onReturn={() => {}} navigationNote="" />
  </MemoryRouter></QueryClientProvider>));
  return onNext;
}

describe("chapter-content continuous review interactions", () => {
  it("requires dispositions, keeps the bottom action visible, and advances only after a version-matched success", async () => {
    const item = contentItem();
    const key = contentDraftKey("all", item.review_id, item.chapter_content!);
    sessionStorage.setItem(key, JSON.stringify(readyDraft()));
    vi.mocked(submitChapterContentDecision).mockResolvedValue({ ...item, status: "resolved", chapter_content: {
      ...item.chapter_content!, decision: { ...buildContentDecision(item.chapter_content!, readyDraft(), "accept"), decision_sha256: "9".repeat(64) },
    } });
    const next = await render(item);
    expect(container.querySelector("footer")?.contains(button("接受原样并下一项"))).toBe(true);
    expect(button("接受原样并下一项").disabled).toBe(false);
    await act(async () => button("接受原样并下一项").click());
    expect(submitChapterContentDecision).toHaveBeenCalledTimes(1);
    expect(next).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem(key)).toBeNull();
  });
  it("preserves the draft and current review after a failed or mismatched response", async () => {
    const item = contentItem();
    const key = contentDraftKey("all", item.review_id, item.chapter_content!);
    sessionStorage.setItem(key, JSON.stringify(readyDraft()));
    vi.mocked(submitChapterContentDecision).mockResolvedValue({ ...item, review_id: "another-review", status: "resolved" });
    const next = await render(item);
    await act(async () => button("接受原样并下一项").click());
    expect(next).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(key)).not.toBeNull();
    expect(container.textContent).toContain("核对服务器记录");
  });
  it("disables direct acceptance after editing and offers revision without reusing the old approval", async () => {
    const item = contentItem();
    const draft = readyDraft();
    draft.edits["/translation/blocks/0/text"] = "修改后的完整第一段。";
    sessionStorage.setItem(contentDraftKey("all", item.review_id, item.chapter_content!), JSON.stringify(draft));
    await render(item);
    expect(button("接受原样并下一项").disabled).toBe(true);
    expect(button("提交修订并下一项").disabled).toBe(false);
    expect(container.textContent).toContain("已修改 1 项");
  });
  it("does not apply another review's draft and exposes all saved model records", async () => {
    const item = contentItem();
    sessionStorage.setItem(contentDraftKey("all", "older-review", item.chapter_content!), JSON.stringify(readyDraft()));
    await render(item);
    expect(button("接受原样并下一项").disabled).toBe(true);
    expect(container.textContent).toContain("fixture-a");
    expect(container.textContent).toContain("fixture-b");
    expect(container.querySelectorAll(".ccr-history-record")).toHaveLength(2);
  });
});

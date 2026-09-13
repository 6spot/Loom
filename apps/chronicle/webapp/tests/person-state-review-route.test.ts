// @vitest-environment jsdom
import { act, createElement, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import StudioReviewDetailPage from "../src/pages/studio/StudioReviewDetailPage";
import { StudioAuthProvider } from "../src/lib/studio-auth";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const candidateKey = "psc_000000000000000000000001";
const fingerprint = "f".repeat(64);
let root: Root | undefined;
let client: QueryClient | undefined;
let container: HTMLDivElement;

afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  client?.clear();
  container?.remove();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  root = undefined;
});

async function mount(options: { openReviews?: number; resumeFails?: boolean; wrongReceipt?: boolean; dismissed?: boolean } = {}) {
  const observed = { decisions: 0, resumes: 0, contexts: [] as URL[], resumeFails: options.resumeFails ?? false };
  let status = options.dismissed ? "dismissed" : "open";
  let jobStatus = options.dismissed ? "cancelled" : "needs_review";
  let saved: { rationale: string } | null = null;
  const review = () => ({ review_id: "r1", job_id: "j1", status, scope: "person_state",
    job_status: jobStatus, review_mode: "chapter_state_evidence", created_at: "2026-09-13T00:00:00Z",
    plan_fingerprint: fingerprint, candidate_count: 1, chapter_id: "ch1", catalog_sha: "c".repeat(64),
    default_assessment: "uncertain", allowed_assessments: ["supported", "uncertain"],
    has_more: false, cursor: null, next_cursor: null, limit: 20, decision: saved,
    document: { title: "完整测试章", document_id: "d1" },
    candidates: [{ candidate_key: candidateKey, item_ref: "pf1", kind: "fact", chapter_id: "ch1",
      person_id: "person1", person_name: "测试人物", dimension: "office", value: "测试官职",
      relation: null, target: null, operation: "start", qualification: "ordinary", attribution: "narrator",
      phase_refs: ["ph1"], reason_codes: [], quote: "某人授某职", source_label: "完整测试章",
      assessment_default: "uncertain", allowed_assessments: ["supported", "uncertain"], predicted_effect: "current_identity" }] });
  const response = (value: unknown, code = 200) => new Response(JSON.stringify(value), {
    status: code, headers: { "Content-Type": "application/json" },
  });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/decision")) {
      observed.decisions += 1;
      const body = JSON.parse(String(init?.body));
      expect(body.plan_fingerprint).toBe(fingerprint);
      status = "resolved"; saved = { rationale: body.rationale };
      return response({ review: { ...review(), plan_fingerprint: options.wrongReceipt ? "wrong" : fingerprint } });
    }
    if (url.pathname === "/api/v1/studio/jobs/j1/resume") {
      observed.resumes += 1;
      if (observed.resumeFails) return response({ error: { code: "unavailable", message: "worker unavailable" } }, 503);
      jobStatus = "queued";
      return response({ job: { job_id: "j1", status: jobStatus, open_reviews: 0 } });
    }
    if (url.pathname === "/api/v1/studio/jobs/j1") return response({ job: {
      job_id: "j1", status: jobStatus, open_reviews: options.openReviews ?? 0,
    } });
    if (url.pathname.endsWith("/contexts")) {
      observed.contexts.push(url);
      return response({ review_id: "r1", items: [], total: 0, has_more: false, next_cursor: null });
    }
    if (url.pathname === "/api/v1/studio/jobs/reviews/r1") return response({ review: review() });
    if (url.pathname === "/api/v1/studio/jobs/reviews") return response({ items: [], next_cursor: null,
      open_count: 0, observed_at: "2026-09-13T00:00:00Z", plan_fingerprint: fingerprint });
    throw new Error(`Unexpected route ${url.pathname}`);
  }));
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  container = document.createElement("div"); document.body.appendChild(container);
  root = createRoot(container);
  const tree = createElement(QueryClientProvider, { client: client! },
    createElement(StudioAuthProvider, null,
      createElement(MemoryRouter, { initialEntries: ["/studio/review/r1?review_scope=all&job_id=j1"] },
        createElement(Routes, null, createElement(Route, {
          path: "/studio/review/:reviewId", element: createElement(StudioReviewDetailPage),
        })))));
  await act(async () => root!.render(createElement(StrictMode, null, tree)));
  await settled(() => expect(container.querySelector(options.dismissed
    ? '[data-test="person-state-review-result"]' : '[data-test="person-state-review-panel"]')).not.toBeNull());
  return observed;
}

async function settled(assertion: () => void) {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); });
  await vi.waitFor(assertion);
}
async function click(selector: string) {
  const node = container.querySelector<HTMLButtonElement>(selector);
  expect(node).not.toBeNull();
  await act(async () => node!.click());
}
async function reviewAndSave() {
  await click('[data-test="psr-batch-confirm"]');
  const field = container.querySelector<HTMLTextAreaElement>('[data-test="psr-rationale"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field, "已核对完整章及阶段，不外推任期。");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click('[data-test="psr-save-next"]');
}

it("loads only the requested candidate's original context without changing the draft", async () => {
  const observed = await mount();
  expect(observed.contexts).toHaveLength(0);
  await click('[data-test="psr-source-slot"] button');
  await settled(() => expect(observed.contexts).toHaveLength(1));
  expect(observed.contexts[0].searchParams.get("candidate_id")).toBe(candidateKey);
  expect(observed.contexts[0].searchParams.has("group_id")).toBe(false);
  expect(container.querySelector('[data-test="psr-candidate"]')?.getAttribute("data-reviewed")).toBe("false");
  expect(observed.decisions).toBe(0);
});

it("continues the job after the last review and shows a read-only saved record", async () => {
  const observed = await mount();
  await reviewAndSave();
  await settled(() => expect(observed.resumes).toBe(1));
  expect(observed.decisions).toBe(1);
  expect(container.querySelector('[data-test="person-state-review-result"]')).not.toBeNull();
  expect(container.querySelector('[data-test="psr-save-next"]')).toBeNull();
  expect(container.querySelector('[data-test="psr-assessment"]')).toBeNull();
  expect(container.textContent).toContain("已核对完整章及阶段");
});

it("does not resume when another scope still has pending reviews", async () => {
  const observed = await mount({ openReviews: 1 });
  await reviewAndSave();
  await settled(() => expect(container.textContent).toContain("还有 1 项待审"));
  expect(observed.resumes).toBe(0);
  expect(observed.decisions).toBe(1);
});

it("retries only continuation after a resume failure without resubmitting the decision", async () => {
  const observed = await mount({ resumeFails: true });
  await reviewAndSave();
  await settled(() => expect(container.textContent).toContain("继续生产未成功"));
  expect(container.querySelector('[data-test="psr-save-next"]')).toBeNull();
  observed.resumeFails = false;
  const retry = [...container.querySelectorAll("button")].find(button => button.textContent === "继续生产")!;
  await act(async () => retry.click());
  await settled(() => expect(observed.resumes).toBe(2));
  expect(observed.decisions).toBe(1);
});

it("keeps the draft and refuses continuation on a mismatched receipt", async () => {
  const observed = await mount({ wrongReceipt: true });
  await reviewAndSave();
  await settled(() => expect(container.textContent).toContain("服务器返回的审核版本不一致"));
  expect(container.querySelector('[data-test="person-state-review-result"]')).toBeNull();
  expect(container.querySelector<HTMLTextAreaElement>('[data-test="psr-rationale"]')?.value).toContain("已核对完整章");
  expect(observed.resumes).toBe(0);
});

it("never shows an editable form or continuation on a cancelled package", async () => {
  const observed = await mount({ dismissed: true });
  expect(container.querySelector('[data-test="psr-save-next"]')).toBeNull();
  expect(container.textContent).toContain("本次任务已取消");
  expect([...container.querySelectorAll("button")].some(button => button.textContent === "继续生产")).toBe(false);
  expect(observed.resumes).toBe(0);
});

// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { memoryStorage, ReviewSessionStore, parseReviewSearch } from "../src/lib/review-session";
import type { ReviewScope } from "../src/lib/review-session";
import type { PersonStateReviewDraft } from "../src/lib/person-state-review-display";
import type { ReviewPackage } from "../src/lib/person-state-types";
import { usePersonStateDraft } from "../src/pages/studio/StudioReviewDetailPage";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const root = process.cwd();
const read = (relative: string) => readFileSync(`${root}/src/${relative}`, "utf-8");

const historyPage = read("pages/public/HistoryPage.tsx");
const readingPage = read("pages/public/ReadingPage.tsx");
const entityPage = read("pages/public/EntityPage.tsx");
const reviewPage = read("pages/studio/StudioReviewPage.tsx");
const reviewDetail = read("pages/studio/StudioReviewDetailPage.tsx");

describe("main history phase context wiring", () => {
  it("subscribes the one reading controller to the phase context hook", () => {
    expect(historyPage).toContain("useHistoryPersonStateContext");
    expect(historyPage).toContain("phaseContext.stateFacts");
    expect(historyPage).toContain("contextFor(phaseContext.entities)");
    // One controller only: no second scroll/history controller.
    expect(historyPage.match(/useReadingPosition\(/g)?.length).toBe(1);
  });

  it("carries version, paragraph and phase to the entity page and back", () => {
    expect(historyPage).toContain("&version=${pub.version}&para=");
    expect(historyPage).toContain("&phase=");
    expect(entityPage).toContain("HistoryReturnLink");
  });
});

describe("entity page phase and source return", () => {
  it("reads the phase/paragraph locator and keeps a direct-entry semantic", () => {
    expect(entityPage).toContain('params.get("phase")');
    expect(entityPage).toContain('params.get("para")');
    expect(entityPage).toContain("HistoryPhasePanel");
    expect(entityPage).toContain("直接进入人物页");
  });

  it("uses the full compiled PersonSummary from the source locator, not a name guess", () => {
    expect(entityPage).toContain("useSourcePersonStateContext");
    expect(entityPage).toContain("PersonStateDetails");
    expect(entityPage).toContain("source.people.find");
    expect(entityPage).toContain("不按名称或年份猜一份身份");
  });
});

describe("source reading person state", () => {
  it("mounts the T11 compact component with the active unit locator", () => {
    expect(readingPage).toContain("useSourcePersonStateContext");
    expect(readingPage).toContain("PersonStateItems");
    expect(readingPage).toContain("stage={");
    expect(readingPage).toContain("onOpenDetails");
  });
});

describe("studio mixed review scope", () => {
  it("defaults the queue to all and sends review_scope through", () => {
    expect(reviewPage).toContain("reviewScope: scope.reviewScope");
    expect(reviewPage).toContain("SCOPE_FILTERS");
    expect(parseReviewSearch("").reviewScope).toBe("all");
  });

  it("dispatches the person-state package to the T12 panel", () => {
    expect(reviewDetail).toContain("PersonStateReviewPanel");
    expect(reviewDetail).toContain('item.scope === "person_state"');
    expect(reviewDetail).toContain("toPersonPackage");
    expect(reviewDetail).toContain("submitPersonStateAssessment");
    expect(reviewDetail).toContain("buildAssessmentOverlay");
  });
});

describe("scope-discriminated drafts", () => {
  const personScope = { status: "open" as const, jobId: null, linkKind: null, reviewScope: "person_state" as const };

  it("keeps the person-state draft out of every other queue family", () => {
    const store = new ReviewSessionStore(memoryStorage());
    store.savePersonStateDraft(personScope, "r1", "fp-1", {
      planFingerprint: "fp-1",
      defaultAssessment: "supported",
      batchApplied: false,
      overrides: {},
      reviewed: {},
      rationale: "阶段依据",
    });
    expect(store.loadPersonStateDraft(personScope, "r1", "fp-1")).toMatchObject({ planFingerprint: "fp-1" });
    expect(store.loadPersonStateDraft({ ...personScope, reviewScope: "all" }, "r1", "fp-1")).toBeNull();
    expect(store.loadDraft("r1", "fp-1", "person_state")).toBeNull();
  });

  it("isolates the resolution decision draft per review_scope", () => {
    const store = new ReviewSessionStore(memoryStorage());
    store.saveDraft("r1", "fp-1", {
      decision: "same_entity",
      rationale: "身份",
      confidence: "0.5",
      showExceptions: false,
      groupOverrides: {},
    }, "resolution");
    expect(store.loadDraft("r1", "fp-1", "resolution")).not.toBeNull();
    expect(store.loadDraft("r1", "fp-1", "all")).toBeNull();
  });
});

// Component-level regression for Reviewer CHANGES_REQUIRED: the person-state
// draft lifecycle must key on review_scope, not only review_id/fingerprint.
// The same review opened via `review_scope=all` and `review_scope=person_state`
// (URL / browser back-forward) must rehydrate each scope's own draft and never
// carry the other scope's content over.
describe("person-state draft lifecycle across URL scope switches", () => {
  const packageFixture: ReviewPackage = {
    schema: "chronicle.person-state-review",
    version: "0.1",
    review_id: "r1",
    plan_fingerprint: "fp-1",
    scope: "person_state",
    review_mode: "chapter_state_evidence",
    chapter_id: "ch1",
    catalog_sha: "a".repeat(64),
    candidates: [],
    candidate_count: 0,
    limit: 20,
    cursor: null,
    next_cursor: null,
    has_more: false,
    default_assessment: "supported",
  };
  const scopeAll: ReviewScope = { status: "open", jobId: null, linkKind: null, reviewScope: "all" };
  const scopePersonState: ReviewScope = { ...scopeAll, reviewScope: "person_state" };
  const containers: HTMLElement[] = [];

  const makeDraft = (rationale: string): PersonStateReviewDraft => ({
    planFingerprint: "fp-1",
    defaultAssessment: "supported",
    batchApplied: false,
    overrides: {},
    reviewed: {},
    rationale,
  });

  function Host({ scope, store }: { scope: ReviewScope; store: ReviewSessionStore }) {
    const [draft] = usePersonStateDraft(scope, packageFixture.review_id, packageFixture, store);
    return createElement("output", { "data-testid": "rationale" }, draft?.rationale ?? "");
  }

  afterEach(() => {
    for (const container of containers.splice(0)) container.remove();
  });

  it("rehydrates per scope and never persists the old scope's draft", async () => {
    const store = new ReviewSessionStore(memoryStorage());
    store.savePersonStateDraft(scopeAll, "r1", "fp-1", makeDraft("all-draft"));
    store.savePersonStateDraft(scopePersonState, "r1", "fp-1", makeDraft("ps-draft"));

    const container = document.createElement("div");
    document.body.appendChild(container);
    containers.push(container);
    const root = createRoot(container);
    const read = () => container.querySelector('[data-testid="rationale"]')?.textContent ?? "";
    const render = async (scope: ReviewScope) => {
      await act(async () => {
        root.render(createElement(Host, { scope, store }));
      });
    };

    // Start on `all`, then switch the URL scope to `person_state` without any
    // review_id/fingerprint change: it must show the person_state draft, not
    // the all draft that is still textually the same review.
    await render(scopeAll);
    expect(read()).toBe("all-draft");

    await render(scopePersonState);
    expect(read()).toBe("ps-draft");
    expect(store.loadPersonStateDraft<PersonStateReviewDraft>(scopeAll, "r1", "fp-1")?.rationale).toBe("all-draft");

    // A scope with no stored draft starts clean, and the still-mounted previous
    // draft is not written into the new scope.
    const emptyStore = new ReviewSessionStore(memoryStorage());
    emptyStore.savePersonStateDraft(scopeAll, "r1", "fp-1", makeDraft("all-draft"));
    const container2 = document.createElement("div");
    document.body.appendChild(container2);
    containers.push(container2);
    const root2 = createRoot(container2);
    const read2 = () => container2.querySelector('[data-testid="rationale"]')?.textContent ?? "";
    await act(async () => {
      root2.render(createElement(Host, { scope: scopeAll, store: emptyStore }));
    });
    expect(read2()).toBe("all-draft");
    await act(async () => {
      root2.render(createElement(Host, { scope: scopePersonState, store: emptyStore }));
    });
    expect(read2()).toBe("");
    expect(emptyStore.loadPersonStateDraft<PersonStateReviewDraft>(scopePersonState, "r1", "fp-1")?.rationale ?? "").not.toBe("all-draft");

    // Back/forward returns to the exact previous scope draft.
    await act(async () => {
      root2.render(createElement(Host, { scope: scopeAll, store: emptyStore }));
    });
    expect(read2()).toBe("all-draft");
  });
});


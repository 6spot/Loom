import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { memoryStorage, ReviewSessionStore, parseReviewSearch } from "../src/lib/review-session";

const root = new URL("..", import.meta.url).pathname;
const read = (relative: string) => readFileSync(`${root}src/${relative}`, "utf-8");

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

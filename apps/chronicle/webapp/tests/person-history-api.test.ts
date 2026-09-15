import { afterEach, describe, expect, it, vi } from "vitest";
import {
  isPersonHistoryParagraph,
  isPersonHistoryVersion,
  loadPersonHistoryPage,
  mappingPhaseIds,
  personHistoryConclusionPath,
  personHistoryMetadataPath,
  personHistoryParagraphsPath,
  type PersonHistoryMapping,
  type PersonHistoryPageResponse,
} from "../src/lib/person-history-api";

const PERSON_ID = "person-zhou-yu";
const MAIN_VERSION = "a".repeat(64);
const PERSON_VERSION = "b".repeat(64);

afterEach(() => vi.unstubAllGlobals());

describe("T13 person-history paths", () => {
  it("pins an independent person version while retaining the exact main locator", () => {
    expect(personHistoryMetadataPath(PERSON_ID, {
      personVersion: PERSON_VERSION,
      mainHistory: { version: MAIN_VERSION, paragraphId: "hp_1234567890abcdef12345678", phaseId: "phase_chibi" },
    })).toBe(`/api/v1/public/entities/${PERSON_ID}/history?version=${MAIN_VERSION}&paragraph_id=hp_1234567890abcdef12345678&phase_id=phase_chibi&person_version=${PERSON_VERSION}`);
    expect(personHistoryParagraphsPath(PERSON_ID, PERSON_VERSION, { start: 50, limit: 50 })).toBe(`/api/v1/public/entities/${PERSON_ID}/history/paragraphs?version=${PERSON_VERSION}&limit=50&start=50`);
    expect(personHistoryConclusionPath(PERSON_ID, PERSON_VERSION, "office_chibi")).toContain(`/conclusions/office_chibi?version=${PERSON_VERSION}`);
  });

  it("rejects unpinned biography reads and invalid paragraph versions", () => {
    expect(isPersonHistoryVersion(PERSON_VERSION)).toBe(true);
    expect(isPersonHistoryVersion("draft")).toBe(false);
    expect(isPersonHistoryParagraph("pp_1234567890abcdef12345678")).toBe(true);
    expect(isPersonHistoryParagraph("hp_1234567890abcdef12345678")).toBe(false);
    expect(() => personHistoryParagraphsPath(PERSON_ID, "draft")).toThrow();
  });
});

describe("T13 mapping semantics", () => {
  it("keeps every ambiguous candidate instead of selecting the first", () => {
    const mapping: PersonHistoryMapping = {
      status: "ambiguous",
      reason: "保留候选",
      request: { version: MAIN_VERSION, paragraph_id: "hp_1234567890abcdef12345678", phase_id: "main_phase" },
      matches: [
        { phase_id: "phase_early", person_phase_id: "phase_early", status: "ambiguous", mapping_status: "ambiguous", reason: "候选一", targets: [] },
        { phase_id: "phase_chibi", person_phase_id: "phase_chibi", status: "ambiguous", mapping_status: "ambiguous", reason: "候选二", targets: [] },
      ],
    };
    expect(mappingPhaseIds(mapping)).toEqual(["phase_early", "phase_chibi"]);
  });
});

describe("T13 response version binding", () => {
  it("does not accept a page projected from another person version", async () => {
    const page: PersonHistoryPageResponse = {
      schema: "chronicle.person-history-page",
      version: "0.1",
      person_id: PERSON_ID,
      person_history_version: MAIN_VERSION,
      publication_version: MAIN_VERSION,
      paragraphs: [],
      start: 0,
      total: 0,
      returned: 0,
      first_paragraph_id: null,
      last_paragraph_id: null,
      previous_start: null,
      next_start: null,
      has_more: false,
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(page), { status: 200, headers: { "Content-Type": "application/json" } })));
    await expect(loadPersonHistoryPage(PERSON_ID, PERSON_VERSION)).rejects.toThrow("人物经历与当前固定版本不一致");
  });
});


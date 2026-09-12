// C2-R3-T01 人物阶段资料共享类型单元测试。
//
// 覆盖 person-state-reading.md §2-2/§5.1/§7 的 client 纪律：certainty 只接受
// 服务端已编译的 clear|uncertain；review_scope 省略保持 resolution、all 覆盖
// 三类；locator 与 state item 的守卫拒绝未编译/错型输入；地点行政归属与实际
// 控制是两个独立维度。全部为合成数据。

import { describe, expect, it } from "vitest";
import {
  ASSESSMENTS,
  DEFAULT_REVIEW_SCOPE,
  PERSON_STATE_LIMITS,
  PLACE_DIMENSIONS,
  REASON_CODES,
  REVIEW_SCOPES,
  STATE_DIMENSIONS,
  isCertainty,
  isPersonStateLocator,
  isReasonCode,
  isStateItem,
  normalizeReviewScope,
  reviewScopeCovers,
} from "../src/lib/person-state-types";

const CATALOG = "a".repeat(64);
const STREAM = "0192f0a0-0000-7000-8000-00000000aa01";
const UNIT = "ru_0123456789abcdef01234567";

function stateItem(overrides: Record<string, unknown> = {}) {
  return {
    item_id: "psi_" + "0".repeat(24),
    person_id: "0192f0a0-0000-7000-8000-00000000cc07",
    dimension: "office",
    value: "建威中郎將",
    relation: null,
    target: null,
    target_id: null,
    qualification: "ordinary",
    certainty: "clear",
    reason_codes: [],
    reason_text: "",
    phase_ids: ["ph_001"],
    current: true,
    source_facts: [],
    evidence_count: 1,
    evidence_cursor: null,
    ...overrides,
  };
}

describe("person-state limits", () => {
  it("mirrors the Python engineering envelope", () => {
    expect(PERSON_STATE_LIMITS.maxPhases).toBe(512);
    expect(PERSON_STATE_LIMITS.maxFacts).toBe(512);
    expect(PERSON_STATE_LIMITS.maxAssertions).toBe(1024);
    expect(PERSON_STATE_LIMITS.maxPhasesPerUnit).toBe(8);
    expect(PERSON_STATE_LIMITS.pageMaxLimit).toBe(50);
    expect(PERSON_STATE_LIMITS.evidencePageMaxDescriptors).toBe(50);
    expect(PERSON_STATE_LIMITS.summaryMaxItems).toBe(3);
  });

  it("keeps the fixed enumerations", () => {
    expect(STATE_DIMENSIONS).toEqual(["office", "title", "affiliation"]);
    expect(PLACE_DIMENSIONS).toEqual(["administration", "control"]);
    expect(REASON_CODES).toContain("tenure_unproven");
    expect(REASON_CODES).toContain("source_disagreement");
    expect(ASSESSMENTS).toContain("rejected");
  });
});

describe("review scope", () => {
  it("omitted scope keeps resolution and all covers every scope", () => {
    expect(normalizeReviewScope(undefined)).toBe(DEFAULT_REVIEW_SCOPE);
    expect(normalizeReviewScope(null)).toBe("resolution");
    expect(normalizeReviewScope("")).toBe("resolution");
    expect(reviewScopeCovers(undefined, "resolution")).toBe(true);
    expect(reviewScopeCovers(undefined, "person_state")).toBe(false);
    expect(reviewScopeCovers("all", "resolution")).toBe(true);
    expect(reviewScopeCovers("all", "person_state")).toBe(true);
    expect(reviewScopeCovers("all", "narrative")).toBe(true);
    expect(REVIEW_SCOPES).toEqual(["resolution", "person_state", "all"]);
  });

  it("rejects unknown scopes", () => {
    expect(() => normalizeReviewScope("narrative")).toThrow(/review_scope/);
  });
});

describe("type guards", () => {
  it("validates a canonical person-state locator", () => {
    expect(isPersonStateLocator({ stream_id: STREAM, catalog_sha: CATALOG, unit_id: UNIT })).toBe(true);
    expect(isPersonStateLocator({ stream_id: "not-a-uuid", catalog_sha: CATALOG, unit_id: UNIT })).toBe(false);
    expect(isPersonStateLocator({ stream_id: STREAM, catalog_sha: "x", unit_id: UNIT })).toBe(false);
  });

  it("accepts only the two compiled certainties and known reason codes", () => {
    expect(isCertainty("clear")).toBe(true);
    expect(isCertainty("uncertain")).toBe(true);
    expect(isCertainty("unclear")).toBe(false);
    expect(isReasonCode("tenure_unproven")).toBe(true);
    expect(isReasonCode("guessed")).toBe(false);
  });

  it("guards a compiled state item and never derives certainty", () => {
    expect(isStateItem(stateItem())).toBe(true);
    expect(isStateItem(stateItem({ certainty: "unclear" }))).toBe(false);
    expect(isStateItem(stateItem({ reason_codes: ["not_a_code"] }))).toBe(false);
    expect(isStateItem(stateItem({ dimension: "control" }))).toBe(false);
  });
});

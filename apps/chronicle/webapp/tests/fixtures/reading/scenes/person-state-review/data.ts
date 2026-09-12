// C2-R3-T12 章阶段依据审核组件 fixture 数据（仅测试使用，不进生产构建）。
//
// 全部为合成 DTO，只演示 T01 `ReviewPackage` 形状与 T12 组件的交互；不是真实
// 史料译文、不是真实模型输出，也不冒充已发布内容。
// - A 包第一页 `has_more=true`，用页 2 证明候选分页可达且草稿按 candidate_key 隔离。
// - B 包复用 A 的部分 candidate_key，证明切换审核项不会沿用上一包草稿。
// - C 包 `has_more=true` 且无下一页，证明组件在候选不可达时 fail closed。

import type { ReviewCandidate, ReviewPackage } from "../../../../../src/lib/person-state-types";

const CATALOG = "ca".repeat(32);
const CHAPTER = "ch_0123456789abcdef01234567";

function key(seed: number): string {
  return `psc_${seed.toString(16).padStart(24, "0")}`;
}

function candidate(seed: number, overrides: Partial<ReviewCandidate> = {}): ReviewCandidate {
  return {
    candidate_key: key(seed),
    kind: "fact",
    chapter_id: CHAPTER,
    item_ref: `pf_${seed}`,
    person_id: "0192f0a0-0000-7000-8000-00000000cc07",
    person_name: "周瑜",
    dimension: "office",
    value: "建威中郎將",
    relation: null,
    target: null,
    operation: "start",
    qualification: "ordinary",
    phase_refs: ["ph_001"],
    predicted_effect: "current",
    assessment_default: "supported",
    allowed_assessments: ["supported", "uncertain", "disputed", "rejected"],
    source_label: "周瑜傳",
    quote: "策授瑜建威中郎將",
    attribution: "narrator",
    reason_codes: [],
    ...overrides,
  };
}

const PACKAGE_A_CANDIDATES: ReviewCandidate[] = [
  candidate(1, {
    person_id: "p-zhouyu",
    person_name: "周瑜",
    dimension: "office",
    value: "建威中郎將",
    phase_refs: ["ph_001"],
    predicted_effect: "current",
    assessment_default: "supported",
  }),
  candidate(2, {
    person_id: "p-zhouyu",
    person_name: "周瑜",
    dimension: "office",
    value: "偏將軍",
    phase_refs: ["ph_002"],
    predicted_effect: "current",
    assessment_default: "supported",
    quote: "權拜瑜偏將軍，領南郡太守",
  }),
  candidate(3, {
    person_id: "p-zhouyu",
    person_name: "周瑜",
    dimension: "office",
    value: "南郡太守",
    phase_refs: ["ph_002"],
    predicted_effect: "current",
    assessment_default: "uncertain",
    reason_codes: ["tenure_unproven"],
    quote: "權拜瑜偏將軍，領南郡太守",
  }),
  candidate(4, {
    person_id: "p-zhouyu",
    person_name: "周瑜",
    dimension: "title",
    value: "前部大督",
    operation: "attest",
    qualification: "reported",
    phase_refs: ["ph_003"],
    predicted_effect: "none",
    assessment_default: "uncertain",
    reason_codes: ["evidence_uncertain"],
    quote: "瑜為前部大督",
  }),
  candidate(5, {
    person_id: "p-liubei",
    person_name: "劉備",
    dimension: "affiliation",
    relation: "attached_to",
    target: "陶謙",
    value: null,
    operation: "start",
    phase_refs: ["ph_004"],
    predicted_effect: "prior",
    assessment_default: "supported",
    quote: "先主遂去楷歸謙",
    attribution: "narrator",
  }),
  candidate(6, {
    person_id: "p-liubei",
    person_name: "劉備",
    dimension: "title",
    value: "宜城亭侯",
    operation: "end",
    qualification: "self_designation",
    phase_refs: ["ph_005"],
    predicted_effect: "ended",
    assessment_default: "disputed",
    reason_codes: ["source_disagreement", "attribution_uncertain"],
    quote: "上還所假左將軍、宜城亭侯印綬",
    attribution: "quotation",
  }),
  candidate(7, {
    person_id: "p-lusu",
    person_name: "魯肅",
    dimension: "office",
    value: "贊軍校尉",
    phase_refs: ["ph_002"],
    predicted_effect: "current",
    assessment_default: "supported",
    quote: "以肅為贊軍校尉",
    source_label: "魯肅傳",
  }),
  candidate(8, {
    person_id: "p-nanjun",
    person_name: "南郡",
    dimension: "administration",
    value: "荊州",
    operation: "attest",
    phase_refs: ["ph_002"],
    predicted_effect: "current",
    assessment_default: "uncertain",
    reason_codes: ["order_unknown"],
    quote: "領南郡太守",
    source_label: "周瑜傳",
  }),
  candidate(9, {
    person_id: "p-nanjun",
    person_name: "南郡",
    dimension: "control",
    value: "周瑜",
    operation: "attest",
    phase_refs: ["ph_002"],
    predicted_effect: "current",
    assessment_default: "uncertain",
    reason_codes: ["source_disagreement"],
    quote: "分南郡之南岸以封瑜",
    source_label: "江表傳",
    attribution: "annotation",
  }),
  candidate(10, {
    person_id: "p-caocao",
    person_name: "曹操",
    dimension: "office",
    value: "丞相",
    phase_refs: ["ph_006"],
    predicted_effect: "prior",
    assessment_default: "supported",
    quote: "漢罷三公官，置丞相",
    source_label: "武帝紀",
  }),
];

// Filler candidates keep the package long enough to prove that every candidate
// is reachable and the action bar stays usable at the bottom of a long page.
const PACKAGE_A_FILLER: ReviewCandidate[] = Array.from({ length: 14 }, (_, index) =>
  candidate(100 + index, {
    person_id: `p-filler-${index % 3}`,
    person_name: ["周瑜", "劉備", "魯肅"][index % 3],
    dimension: index % 3 === 0 ? "office" : index % 3 === 1 ? "title" : "affiliation",
    value: index % 3 === 2 ? null : `合成官職 ${index + 1}`,
    relation: index % 3 === 2 ? "serves" : null,
    target: index % 3 === 2 ? `合成對象 ${index + 1}` : null,
    operation: index % 3 === 2 ? "start" : "attest",
    phase_refs: index % 2 === 0 ? ["ph_002"] : ["ph_005"],
    predicted_effect: index % 2 === 0 ? "current" : "prior",
    assessment_default: index % 4 === 0 ? "uncertain" : "supported",
    quote: `合成原文片段 ${index + 1}`,
    source_label: "合成來源",
  }),
);

const PACKAGE_A_COUNT = PACKAGE_A_CANDIDATES.length + PACKAGE_A_FILLER.length + 16;

export const PACKAGE_A: ReviewPackage = {
  schema: "chronicle.person-state-review",
  version: "0.1",
  review_id: "synth-review-A",
  plan_fingerprint: "a1".repeat(32),
  scope: "person_state",
  review_mode: "chapter_state_evidence",
  chapter_id: CHAPTER,
  catalog_sha: CATALOG,
  candidates: [...PACKAGE_A_CANDIDATES, ...PACKAGE_A_FILLER],
  candidate_count: PACKAGE_A_COUNT,
  limit: 24,
  cursor: null,
  next_cursor: "cur-a-page-2",
  has_more: true,
  default_assessment: "uncertain",
};

const PACKAGE_A_PAGE2_FILLER: ReviewCandidate[] = Array.from({ length: 16 }, (_, index) =>
  candidate(200 + index, {
    person_id: `p-page2-${index % 2}`,
    person_name: index % 2 === 0 ? "周瑜" : "孫權",
    dimension: index % 2 === 0 ? "office" : "affiliation",
    value: index % 2 === 0 ? `合成後頁官職 ${index + 1}` : null,
    relation: index % 2 === 0 ? null : "serves",
    target: index % 2 === 0 ? null : `合成後頁對象 ${index + 1}`,
    operation: "start",
    phase_refs: ["ph_101"],
    predicted_effect: "current",
    assessment_default: "supported",
    quote: `後頁合成原文片段 ${index + 1}`,
    source_label: "合成後頁來源",
  }),
);

export const PACKAGE_A_PAGE2: ReviewPackage = {
  ...PACKAGE_A,
  candidates: PACKAGE_A_PAGE2_FILLER,
  limit: 16,
  cursor: "cur-a-page-2",
  next_cursor: null,
  has_more: false,
};

// Package B reuses candidate_key 1/2/5 with different compiled defaults so the
// browser suite can prove a switched item never inherits the previous draft.
export const PACKAGE_B: ReviewPackage = {
  ...PACKAGE_A,
  review_id: "synth-review-B",
  plan_fingerprint: "b2".repeat(32),
  candidates: [
    candidate(1, {
      person_id: "p-zhouyu",
      person_name: "周瑜",
      dimension: "office",
      value: "建威中郎將（另一章）",
      phase_refs: ["ph_101"],
      predicted_effect: "prior",
      assessment_default: "supported",
    }),
    candidate(2, {
      person_id: "p-zhouyu",
      person_name: "周瑜",
      dimension: "office",
      value: "偏將軍（另一章）",
      phase_refs: ["ph_101"],
      predicted_effect: "prior",
      assessment_default: "supported",
    }),
    candidate(5, {
      person_id: "p-liubei",
      person_name: "劉備",
      dimension: "affiliation",
      relation: "attached_to",
      target: "陶謙",
      value: null,
      operation: "start",
      phase_refs: ["ph_102"],
      predicted_effect: "prior",
      assessment_default: "supported",
    }),
    candidate(50, {
      person_id: "p-sunquan",
      person_name: "孫權",
      dimension: "office",
      value: "討虜將軍",
      phase_refs: ["ph_102"],
      predicted_effect: "current",
      assessment_default: "uncertain",
      reason_codes: ["tenure_unproven"],
      quote: "曹公表權為討虜將軍",
      source_label: "吳主傳",
    }),
  ],
  candidate_count: 4,
  limit: 20,
  cursor: null,
  next_cursor: null,
  has_more: false,
  default_assessment: "uncertain",
};

// C package advertises another page that the scene never provides, so the
// panel must fail closed instead of reviewing an incomplete set.
export const PACKAGE_C: ReviewPackage = {
  ...PACKAGE_A,
  review_id: "synth-review-C",
  plan_fingerprint: "c3".repeat(32),
  candidates: [candidate(300, { person_id: "p-zhouyu", person_name: "周瑜" })],
  candidate_count: 3,
  limit: 1,
  cursor: null,
  next_cursor: "cur-c-page-2",
  has_more: true,
  default_assessment: "uncertain",
};

export const PACKAGES: readonly ReviewPackage[] = [PACKAGE_A, PACKAGE_B];

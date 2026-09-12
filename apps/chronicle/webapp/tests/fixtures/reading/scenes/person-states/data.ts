// C2-R3-T11 组件浏览器场景的合成 DTO 数据（仅测试使用）。
//
// 形状与 T01 的公开 DTO（PersonSummary / PlaceStateItem / PhaseSummary）一致，
// 但全部为合成示例，不是真实史料译文、不是真实模型输出，也不代表已发布内容。
// 其中若干原文核对点（周瑜、刘备）仅用于展示限定语与来源入口的交互。

import type {
  Attribution,
  PersonSummary,
  PhaseSummary,
  PlaceStateItem,
  SourceFactRef,
  StateChange,
  StateItem,
} from "../../../../../src/lib/person-state-types";

export const SYNTHETIC_VERSION = "synthetic-c2r3-t11";
export const PARAGRAPH_ID = "para-208-chibi-03";
export const PHASE_ID = "ph_003";
export const CATALOG_SHA = "a".repeat(64);
export const STREAM_ID = "0192f0a0-0000-7000-8000-00000000aa01";
export const UNIT_ID = "ru_0123456789abcdef01234567";
export const PUBLICATION_ID = "0192f0a0-0000-7000-8000-00000000bb02";
export const MANIFEST_SHA = "33e38d1f0adf9ab53ec1c33af2ba93ba8c3fdf16179de9603df9d67ebe2d3230";

const ZHOUYU = "0192f0a0-0000-7000-8000-00000000cc07";
const LIUBEI = "0192f0a0-0000-7000-8000-00000000cc08";
const LIMENG = "0192f0a0-0000-7000-8000-00000000cc09";
const LUSU = "0192f0a0-0000-7000-8000-00000000cc0a";
const ENVOY = "0192f0a0-0000-7000-8000-00000000cc0b";
const SOMEGENERAL = "0192f0a0-0000-7000-8000-00000000cc0c";
const NANJUN = "0192f0a0-0000-7000-8000-00000000dd08";
const JIANGLING = "0192f0a0-0000-7000-8000-00000000dd09";
const CHAPTER_ID = "ch_756922e9af0d759d29d7475f";
const CHAPTER_PUB_ID = "0192f0a0-0000-7000-8000-00000000bb02";

export const PHASES: readonly PhaseSummary[] = [
  { phase_id: "ph_001", label: "建安三年·还吴", ordinal: 0, mode: "single" },
  { phase_id: "ph_002", label: "前部大督", ordinal: 1, mode: "process" },
  { phase_id: "ph_003", label: "偏将军兼南郡太守", ordinal: 2, mode: "process" },
];

function factRef(ref: string, phaseId: string): SourceFactRef {
  return {
    chapter_publication_id: CHAPTER_PUB_ID,
    chapter_id: CHAPTER_ID,
    revision_id: "rev_c2r3_t11_demo",
    fact_ref: ref,
    claim_refs: [],
    phase_id: phaseId,
  };
}

interface ItemSeed {
  readonly id: string;
  readonly person: string;
  readonly dimension: StateItem["dimension"];
  readonly value?: string | null;
  readonly relation?: StateItem["relation"];
  readonly target?: string | null;
  readonly targetId?: string | null;
  readonly qualification?: StateItem["qualification"];
  readonly certainty: StateItem["certainty"];
  readonly reasonCodes?: StateItem["reason_codes"];
  readonly reasonText?: string;
  readonly phaseId: string;
  readonly current: boolean;
  readonly fact: string;
}

function item(seed: ItemSeed): StateItem {
  return {
    item_id: seed.id,
    person_id: seed.person,
    dimension: seed.dimension,
    value: seed.value ?? null,
    relation: seed.relation ?? null,
    target: seed.target ?? null,
    target_id: seed.targetId ?? null,
    qualification: seed.qualification ?? "ordinary",
    certainty: seed.certainty,
    reason_codes: seed.reasonCodes ?? [],
    reason_text: seed.reasonText ?? "",
    phase_ids: [seed.phaseId],
    current: seed.current,
    source_facts: [factRef(seed.fact, seed.phaseId)],
    evidence_count: 1,
    evidence_cursor: null,
  };
}

const zhouYuItems: readonly StateItem[] = [
  item({
    id: "zy-office-pianjiangjun",
    person: ZHOUYU,
    dimension: "office",
    value: "偏将军",
    certainty: "clear",
    phaseId: "ph_003",
    current: true,
    fact: "pf_zy_pianjiangjun",
  }),
  item({
    id: "zy-office-nanjun",
    person: ZHOUYU,
    dimension: "office",
    value: "领南郡太守",
    certainty: "clear",
    phaseId: "ph_003",
    current: true,
    fact: "pf_zy_nanjun",
  }),
  item({
    id: "zy-office-jianwei",
    person: ZHOUYU,
    dimension: "office",
    value: "建威中郎将",
    certainty: "uncertain",
    reasonCodes: ["tenure_unproven"],
    reasonText: "仅能证明此前受任，缺少本段仍在任的依据，且未见已证明结束。",
    qualification: "reported",
    phaseId: "ph_001",
    current: false,
    fact: "pf_zy_jianwei",
  }),
];

const liuBeiItems: readonly StateItem[] = [
  item({
    id: "lb-title-yicheng",
    person: LIUBEI,
    dimension: "title",
    value: "宜城亭侯",
    certainty: "clear",
    qualification: "reported",
    phaseId: "ph_001",
    current: true,
    fact: "pf_lb_yicheng",
  }),
  item({
    id: "lb-office-zuo",
    person: LIUBEI,
    dimension: "office",
    value: "左将军",
    certainty: "uncertain",
    reasonCodes: ["attribution_uncertain"],
    reasonText: "奏章为自述，未证明朝廷收讫，也未见其他来源承认。",
    qualification: "reported",
    phaseId: "ph_001",
    current: false,
    fact: "pf_lb_zuo",
  }),
  item({
    id: "lb-affiliation-taoqian",
    person: LIUBEI,
    dimension: "affiliation",
    relation: "attached_to",
    target: "陶谦",
    certainty: "clear",
    phaseId: "ph_001",
    current: true,
    fact: "pf_lb_taoqian",
  }),
];

const zhouYuChanges: readonly StateChange[] = [
  {
    item_id: "zy-change-pianjiangjun",
    person_id: ZHOUYU,
    dimension: "office",
    value: "偏将军",
    relation: null,
    target: null,
    operation: "start",
    from_phase_id: "ph_002",
    to_phase_id: "ph_003",
    certainty: "clear",
    reason_codes: [],
    source_facts: [factRef("pf_zy_pianjiangjun", "ph_003")],
  },
  {
    item_id: "zy-change-nanjun",
    person_id: ZHOUYU,
    dimension: "office",
    value: "领南郡太守",
    relation: null,
    target: null,
    operation: "start",
    from_phase_id: null,
    to_phase_id: "ph_003",
    certainty: "clear",
    reason_codes: [],
    source_facts: [factRef("pf_zy_nanjun", "ph_003")],
  },
  {
    item_id: "zy-change-jianwei",
    person_id: ZHOUYU,
    dimension: "office",
    value: "建威中郎将",
    relation: null,
    target: null,
    operation: "start",
    from_phase_id: null,
    to_phase_id: "ph_001",
    certainty: "uncertain",
    reason_codes: ["tenure_unproven"],
    source_facts: [factRef("pf_zy_jianwei", "ph_001")],
  },
];

/** A person whose summary already paginated identities; the scene loads more. */
export const ZHOUYU_SUMMARY: PersonSummary = {
  person_id: ZHOUYU,
  name: "周瑜",
  importance: "primary",
  phase_mode: "single",
  certainty: "uncertain",
  identities: zhouYuItems,
  identity_count: 5,
  has_more_identities: true,
  identity_cursor: "cursor-zy-1",
  changes: zhouYuChanges,
  change_count: zhouYuChanges.length,
  has_more_changes: false,
  change_cursor: null,
  reason_codes: ["tenure_unproven"],
};

export const ZHOUYU_MORE_ITEMS: readonly StateItem[] = [
  item({
    id: "zy-office-taishou",
    person: ZHOUYU,
    dimension: "office",
    value: "江夏太守",
    certainty: "uncertain",
    reasonCodes: ["order_unknown"],
    reasonText: "同年先后未明，不作为当前身份候选。",
    phaseId: "ph_001",
    current: false,
    fact: "pf_zy_jiangxia",
  }),
  item({
    id: "zy-affiliation-sunquan",
    person: ZHOUYU,
    dimension: "affiliation",
    relation: "serves",
    target: "孙权",
    targetId: "0192f0a0-0000-7000-8000-0000000000ee",
    certainty: "clear",
    phaseId: "ph_003",
    current: true,
    fact: "pf_zy_sunquan",
  }),
];

export const LIUBEI_SUMMARY: PersonSummary = {
  person_id: LIUBEI,
  name: "刘备",
  importance: "primary",
  phase_mode: "single",
  certainty: "uncertain",
  identities: liuBeiItems,
  identity_count: liuBeiItems.length,
  has_more_identities: false,
  identity_cursor: null,
  changes: [
    {
      item_id: "lb-change-taoqian",
      person_id: LIUBEI,
      dimension: "affiliation",
      value: null,
      relation: "attached_to",
      target: "陶谦",
      operation: "start",
      from_phase_id: "ph_001",
      to_phase_id: "ph_001",
      certainty: "clear",
      reason_codes: [],
      source_facts: [factRef("pf_lb_taoqian", "ph_001")],
    },
  ],
  change_count: 1,
  has_more_changes: false,
  change_cursor: null,
  reason_codes: ["attribution_uncertain"],
};

export const LIMENG_SUMMARY: PersonSummary = {
  person_id: LIMENG,
  name: "吕蒙",
  importance: "other",
  phase_mode: "process",
  certainty: "clear",
  identities: [
    item({ id: "lm-stage-1", person: LIMENG, dimension: "office", value: "别部司马", certainty: "clear", phaseId: "ph_001", current: false, fact: "pf_lm_1" }),
    item({ id: "lm-stage-2", person: LIMENG, dimension: "office", value: "寻阳令", certainty: "clear", phaseId: "ph_002", current: false, fact: "pf_lm_2" }),
  ],
  identity_count: 2,
  has_more_identities: false,
  identity_cursor: null,
  changes: [],
  change_count: 0,
  has_more_changes: false,
  change_cursor: null,
  reason_codes: [],
};

export const LUSU_SUMMARY: PersonSummary = {
  person_id: LUSU,
  name: "鲁肃",
  importance: "other",
  phase_mode: "ambiguous",
  certainty: "uncertain",
  identities: [
    item({
      id: "ls-amb-1",
      person: LUSU,
      dimension: "office",
      value: "赞军校尉（本段已任）",
      certainty: "uncertain",
      reasonCodes: ["evidence_uncertain"],
      reasonText: "该解释可用于本段，但来源顺序不足以唯一确定。",
      phaseId: "ph_002",
      current: false,
      fact: "pf_ls_1",
    }),
    item({
      id: "ls-amb-2",
      person: LUSU,
      dimension: "office",
      value: "赞军校尉（本段之后）",
      certainty: "uncertain",
      reasonCodes: ["order_unknown"],
      reasonText: "同日／同月先后未明，不作为当前身份候选。",
      phaseId: "ph_003",
      current: false,
      fact: "pf_ls_2",
    }),
  ],
  identity_count: 2,
  has_more_identities: false,
  identity_cursor: null,
  changes: [],
  change_count: 0,
  has_more_changes: false,
  change_cursor: null,
  reason_codes: ["evidence_uncertain"],
};

/** Stage could not be located: not a prior post, not a current candidate. */
export const ENVOY_SUMMARY: PersonSummary = {
  person_id: ENVOY,
  name: "使者",
  importance: "other",
  phase_mode: "unknown",
  certainty: "uncertain",
  identities: [],
  identity_count: 0,
  has_more_identities: false,
  identity_cursor: null,
  changes: [],
  change_count: 0,
  has_more_changes: false,
  change_cursor: null,
  reason_codes: ["order_unknown"],
};

/** No material at all: distinct from stage_unknown. */
export const SOMEGENERAL_SUMMARY: PersonSummary = {
  person_id: SOMEGENERAL,
  name: "某将",
  importance: "other",
  phase_mode: "single",
  certainty: "clear",
  identities: [],
  identity_count: 0,
  has_more_identities: false,
  identity_cursor: null,
  changes: [],
  change_count: 0,
  has_more_changes: false,
  change_cursor: null,
  reason_codes: [],
};

export const PEOPLE: readonly PersonSummary[] = [
  ZHOUYU_SUMMARY,
  LIUBEI_SUMMARY,
  LIMENG_SUMMARY,
  LUSU_SUMMARY,
  SOMEGENERAL_SUMMARY,
  ENVOY_SUMMARY,
];

export const PLACES: readonly PlaceStateItem[] = [
  {
    item_id: "nj-admin-jingzhou",
    place_id: NANJUN,
    name: "南郡",
    dimension: "administration",
    value: "荆州",
    controller: null,
    certainty: "clear",
    reason_codes: [],
    reason_text: "",
    phase_ids: ["ph_003"],
    current: true,
    source_facts: [factRef("pf_nj_admin", "ph_003")],
    evidence_count: 1,
    evidence_cursor: null,
  },
  {
    item_id: "nj-control-caoren",
    place_id: NANJUN,
    name: "南郡",
    dimension: "control",
    value: "曹仁（此前）",
    controller: null,
    certainty: "uncertain",
    reason_codes: ["source_disagreement"],
    reason_text: "两来源对本段控制归属说法不同，保留双方，不取胜者。",
    phase_ids: ["ph_003"],
    current: false,
    source_facts: [factRef("pf_nj_caoren", "ph_003")],
    evidence_count: 1,
    evidence_cursor: null,
  },
  {
    item_id: "nj-control-liubei",
    place_id: NANJUN,
    name: "南郡",
    dimension: "control",
    value: "刘备（借荆州）",
    controller: null,
    certainty: "uncertain",
    reason_codes: ["source_disagreement"],
    reason_text: "另一来源作刘备，阶段适用性尚未一致。",
    phase_ids: ["ph_003"],
    current: false,
    source_facts: [factRef("pf_nj_liubei", "ph_003")],
    evidence_count: 1,
    evidence_cursor: null,
  },
  {
    item_id: "jl-control-zhouyu",
    place_id: JIANGLING,
    name: "江陵",
    dimension: "control",
    value: "周瑜（本段）",
    controller: null,
    certainty: "clear",
    reason_codes: [],
    reason_text: "",
    phase_ids: ["ph_003"],
    current: true,
    source_facts: [factRef("pf_jl_zhouyu", "ph_003")],
    evidence_count: 1,
    evidence_cursor: null,
  },
];

/** Reviewed,精选 entry_points only; not every extracted Event. */
export const EVENTS_BY_ITEM: Readonly<Record<string, readonly { eventRef: string; label: string }[]>> = {
  "zy-office-pianjiangjun": [{ eventRef: "ev-nanjun", label: "南郡之战" }],
  "zy-office-jianwei": [{ eventRef: "ev-jiangxia", label: "江夏之战" }],
  "nj-control-caoren": [{ eventRef: "ev-nanjun", label: "南郡之战" }],
};

export const ATTRIBUTION_BY_ITEM: Readonly<Record<string, Attribution>> = {
  "zy-office-pianjiangjun": "narrator",
  "zy-office-jianwei": "annotation",
  "lb-title-yicheng": "quotation",
  "lb-office-zuo": "quotation",
  "zy-change-jianwei": "annotation",
};

export const PARAGRAPHS: readonly string[] = [
  "建安十三年，孙权拜周瑜为偏将军，领南郡太守。瑜时与程普为左右督，各领万人，与曹公遇于赤壁。",
  "先主遂去楷归谦；其上还所假左将军、宜城亭侯印绶之事，见于奏章。",
  "南郡、江陵的归属与控制在材料中交互出现，须分别依阶段判断。",
];

export const INTRO_TEXT =
  "周瑜，字公瑾，庐江舒人。本段只显示来源支持的当时记载，不从常识补写生平。";

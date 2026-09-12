// C2-R3-T11 人物阶段资料展示投影单元测试（合成数据）。
//
// 覆盖 person-state-reading.md §§2、8 的展示纪律：两档明确性只取服务端结果、
// 限定语/原因可见、兼任并列、行政归属与实际控制分开、暂无记载与阶段未明确
// 是不同空态、变化按服务端阶段顺序展开。全部为合成 DTO。

import { describe, expect, it } from "vitest";
import type {
  PersonSummary,
  PlaceStateItem,
  SourceFactRef,
  StateChange,
  StateItem,
} from "../src/lib/person-state-types";
import {
  CERTAINTY_MARKS,
  EMPTY_STATE_LABELS,
  OPERATION_LABELS,
  PHASE_MODE_LABELS,
  buildChangeTimeline,
  buildReasonText,
  certaintyLabel,
  certaintyMark,
  emptyStateForPerson,
  groupUnitState,
  moreItemsText,
  placeItemView,
  reasonLabel,
  stateItemView,
} from "../src/lib/person-state-display";

const PERSON_ID = "0192f0a0-0000-7000-8000-00000000cc07";
const PLACE_ID = "0192f0a0-0000-7000-8000-00000000dd08";

function sourceFact(overrides: Partial<SourceFactRef> = {}): SourceFactRef {
  return {
    chapter_publication_id: "0192f0a0-0000-7000-8000-00000000bb02",
    chapter_id: "ch_756922e9af0d759d29d7475f",
    revision_id: "rev_c2r3_demo_001",
    fact_ref: "pf_001",
    claim_refs: [],
    phase_id: "ph_001",
    ...overrides,
  };
}

function stateItem(overrides: Partial<StateItem> = {}): StateItem {
  return {
    item_id: "psi_" + "0".repeat(24),
    person_id: PERSON_ID,
    dimension: "office",
    value: "建威中郎将",
    relation: null,
    target: null,
    target_id: null,
    qualification: "ordinary",
    certainty: "clear",
    reason_codes: [],
    reason_text: "",
    phase_ids: ["ph_001"],
    current: true,
    source_facts: [sourceFact()],
    evidence_count: 1,
    evidence_cursor: null,
    ...overrides,
  };
}

function person(overrides: Partial<PersonSummary> = {}): PersonSummary {
  return {
    person_id: PERSON_ID,
    name: "周瑜",
    importance: "primary",
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
    ...overrides,
  };
}

function placeItem(overrides: Partial<PlaceStateItem> = {}): PlaceStateItem {
  return {
    item_id: "psi_" + "1".repeat(24),
    place_id: PLACE_ID,
    name: "南郡",
    dimension: "administration",
    value: "孙权",
    controller: null,
    certainty: "clear",
    reason_codes: [],
    reason_text: "",
    phase_ids: ["ph_003"],
    current: true,
    source_facts: [sourceFact()],
    evidence_count: 1,
    evidence_cursor: null,
    ...overrides,
  };
}

function change(overrides: Partial<StateChange> = {}): StateChange {
  return {
    item_id: "psi_" + "2".repeat(24),
    person_id: PERSON_ID,
    dimension: "office",
    value: "偏将军",
    relation: null,
    target: null,
    operation: "start",
    from_phase_id: "ph_002",
    to_phase_id: "ph_003",
    certainty: "clear",
    reason_codes: [],
    source_facts: [sourceFact({ fact_ref: "pf_002" })],
    ...overrides,
  };
}

describe("certainty marks and labels", () => {
  it("uses the two fixed marks and never invents unclear", () => {
    expect(certaintyMark("clear")).toBe("●");
    expect(certaintyMark("uncertain")).toBe("○");
    expect(CERTAINTY_MARKS.clear).not.toBe(CERTAINTY_MARKS.uncertain);
    expect(certaintyLabel("clear")).toBe("明确");
    expect(certaintyLabel("uncertain")).toBe("存疑");
  });

  it("keeps stable reason and phase labels", () => {
    expect(reasonLabel("tenure_unproven")).toBe("任期未明");
    expect(reasonLabel("source_disagreement")).toBe("来源分歧");
    expect(PHASE_MODE_LABELS.unknown).toBe("阶段未明确");
    expect(EMPTY_STATE_LABELS.stage_unknown).toBe("阶段未明确");
    expect(EMPTY_STATE_LABELS.no_record).toBe("暂无记载");
  });
});

describe("state item views", () => {
  it("renders each concurrent item on its own and keeps qualification visible", () => {
    const office = stateItemView(stateItem({ item_id: "i-office", value: "偏将军" }));
    const concurrent = stateItemView(
      stateItem({ item_id: "i-concurrent", value: "领南郡太守", dimension: "office" }),
    );
    expect(office.valueText).toBe("偏将军");
    expect(concurrent.valueText).toBe("领南郡太守");
    expect(office.valueText).not.toBe(concurrent.valueText);
  });

  it("keeps the qualification text for reported / recommendation and drops ordinary", () => {
    const reported = stateItemView(
      stateItem({ qualification: "reported", value: "前部大督", certainty: "uncertain" }),
    );
    expect(reported.qualificationText).toBe("引述记载");
    const recommendation = stateItemView(stateItem({ qualification: "recommendation" }));
    expect(recommendation.qualificationText).toContain("不建立当前任职");
    expect(stateItemView(stateItem({ qualification: "ordinary" })).qualificationText).toBeNull();
  });

  it("keeps the self-designation qualifier on the conclusion", () => {
    const self = stateItemView(
      stateItem({ qualification: "self_designation", value: "左将军", certainty: "uncertain" }),
    );
    expect(self.qualificationText).toBe("自称");
    expect(self.accessibleText).toContain("自称");
  });

  it("renders the affiliation relation once and keeps the target as the value", () => {
    const view = stateItemView(
      stateItem({
        dimension: "affiliation",
        value: null,
        relation: "serves",
        target: "孙权",
        target_id: "0192f0a0-0000-7000-8000-0000000000ee",
      }),
    );
    expect(view.labelText).toBe("效力");
    expect(view.valueText).toBe("孙权");
    expect(`${view.labelText}${view.valueText}`).toBe("效力孙权");
    expect(view.accessibleText).toContain("效力");
    expect(view.accessibleText).toContain("孙权");
    expect(view.accessibleText.match(/效力/g)?.length).toBe(1);
    const attached = stateItemView(
      stateItem({ dimension: "affiliation", relation: "attached_to", target: "陶谦" }),
    );
    expect(attached.labelText).toBe("归附");
    expect(attached.valueText).toBe("陶谦");
  });

  it("prefers the server reason text and falls back to stable codes", () => {
    const serverText = stateItemView(
      stateItem({ certainty: "uncertain", reason_codes: ["tenure_unproven"], reason_text: "服务端说明" }),
    );
    expect(serverText.reasonText).toBe("服务端说明");
    const derived = stateItemView(
      stateItem({ certainty: "uncertain", reason_codes: ["source_disagreement"], reason_text: "" }),
    );
    expect(derived.reasonText).toBe("来源分歧");
    expect(buildReasonText([], "  ")).toBeNull();
  });

  it("builds an accessible name that carries mark, qualifier and reason", () => {
    const view = stateItemView(
      stateItem({ certainty: "uncertain", reason_codes: ["order_unknown"], value: "赞军校尉" }),
    );
    expect(view.accessibleText).toContain("存疑");
    expect(view.accessibleText).toContain("先后未明");
    expect(view.accessibleText).toContain("赞军校尉");
  });
});

describe("place item views", () => {
  it("keeps administration and control separate", () => {
    const admin = placeItemView(placeItem({ dimension: "administration", value: "荆州" }));
    const control = placeItemView(
      placeItem({ dimension: "control", value: null, controller: "曹仁", certainty: "uncertain" }),
    );
    expect(admin.labelText).toBe("行政归属");
    expect(admin.valueText).toBe("荆州");
    expect(control.labelText).toBe("实际控制");
    expect(control.valueText).toBe("曹仁");
    expect(control.certainty).toBe("uncertain");
  });
});

describe("empty states", () => {
  it("distinguishes no record from stage unknown and never fabricates an item", () => {
    expect(emptyStateForPerson(person({ identities: [stateItem()] }))).toBeNull();
    expect(emptyStateForPerson(person({ identities: [], phase_mode: "unknown" }))).toBe("stage_unknown");
    expect(emptyStateForPerson(person({ identities: [], phase_mode: "single" }))).toBe("no_record");
  });
});

describe("grouping", () => {
  it("defaults to primary people and lists every place separately", () => {
    const groups = groupUnitState(
      [person(), person({ person_id: "p2", importance: "other" })],
      [placeItem()],
    );
    expect(groups.primary.map((entry) => entry.person_id)).toEqual([PERSON_ID]);
    expect(groups.other.map((entry) => entry.person_id)).toEqual(["p2"]);
    expect(groups.places).toHaveLength(1);
    expect(moreItemsText(2)).toBe("更多 · 2");
  });
});

describe("change timeline", () => {
  const phases = [
    { phase_id: "ph_002", label: "前部大督", ordinal: 1, mode: "process" as const },
    { phase_id: "ph_003", label: "偏将军兼南郡太守", ordinal: 2, mode: "process" as const },
  ];

  it("expands changes in server phase order with operation labels", () => {
    const timeline = buildChangeTimeline([change()], phases);
    expect(timeline).toHaveLength(1);
    expect(timeline[0].phaseLabel).toBe("偏将军兼南郡太守");
    expect(timeline[0].fromPhaseLabel).toBe("前部大督");
    expect(timeline[0].operationLabel).toBe(OPERATION_LABELS.start);
    expect(timeline[0].valueText).toBe("偏将军");
    expect(timeline[0].accessibleText).toContain("取得／归附");
  });

  it("keeps uncertain changes marked with a reason", () => {
    const timeline = buildChangeTimeline(
      [change({ certainty: "uncertain", reason_codes: ["evidence_uncertain"] })],
      phases,
    );
    expect(timeline[0].certainty).toBe("uncertain");
    expect(timeline[0].reasonText).toBe("证据未能确定");
  });

  it("renders an affiliation change with the relation label only once", () => {
    const timeline = buildChangeTimeline(
      [
        change({
          dimension: "affiliation",
          value: null,
          relation: "attached_to",
          target: "陶谦",
          operation: "start",
        }),
      ],
      phases,
    );
    expect(timeline[0].dimensionLabel).toBe("归附");
    expect(timeline[0].valueText).toBe("陶谦");
    expect(`${timeline[0].dimensionLabel}${timeline[0].valueText}`).toBe("归附陶谦");
    expect(timeline[0].accessibleText).toContain("归附陶谦");
  });

  it("is empty when there are no reviewed changes", () => {
    expect(buildChangeTimeline([], phases)).toHaveLength(0);
    expect(buildChangeTimeline(null, null)).toHaveLength(0);
  });
});

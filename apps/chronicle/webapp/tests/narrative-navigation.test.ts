import { describe, expect, it } from "vitest";
import { synchronizeNarrativeNavigation } from "../src/lib/narrative-navigation";
import type { NarrativeProse } from "../src/lib/narrative-types";

function draft(): NarrativeProse {
  return { schema: "chronicle.historical-narrative", version: "0.1",
    paragraphs: [0, 1, 2].map((n) => ({ id: `n${n}`, phase_id: `p${n}`, entities: [], segments: [] })),
    entry_points: [{ label: "赤壁之战", kind: "period", paragraph_id: "n0", event_id: null, reason: "改变局势的主要战事" }],
    navigation: [
      { label: "208 年", first_paragraph_id: "n0", last_paragraph_id: "n1", items: [] },
      { label: null, first_paragraph_id: "n2", last_paragraph_id: "n2", items: [] },
    ] };
}

describe("one reviewed entry list supplies every axis node", () => {
  it("moves, renames and removes entries without changing prose, phases or unknown dates", () => {
    const initial = synchronizeNarrativeNavigation(draft());
    const before = structuredClone(initial);
    const moved = synchronizeNarrativeNavigation({ ...initial, entry_points: [{
      ...initial.entry_points[0], paragraph_id: "n2", label: "南郡争夺", reason: "后续独立发展的战事",
    }] });
    expect(initial).toEqual(before);
    expect(moved.paragraphs).toBe(initial.paragraphs);
    expect(moved.navigation?.[0].items).toEqual([]);
    expect(moved.navigation?.[1]).toEqual({ label: null, first_paragraph_id: "n2", last_paragraph_id: "n2",
      items: [{ paragraph_id: "n2", label: "南郡争夺", reason: "后续独立发展的战事" }] });
    const removed = synchronizeNarrativeNavigation({ ...moved, entry_points: [] });
    expect(removed.navigation?.flatMap((section) => section.items)).toEqual([]);
    expect(removed.paragraphs).toBe(initial.paragraphs);
  });

  it("drops legacy extra nodes and does not invent a node when a range is split", () => {
    const original = draft();
    original.navigation![0].items = [{ paragraph_id: "n1", label: "从这段读起", reason: "旧版补位" }];
    original.navigation!.splice(1, 0, { label: null, first_paragraph_id: "n1", last_paragraph_id: "n1", items: [] });
    original.navigation![0].last_paragraph_id = "n0";
    const result = synchronizeNarrativeNavigation(original);
    expect(result.navigation?.map((section) => section.items.length)).toEqual([1, 0, 0]);
    expect(result.navigation?.flatMap((section) => section.items.map((item) => item.label))).toEqual(["赤壁之战"]);
    expect(result.entry_points).toBe(original.entry_points);
  });
});

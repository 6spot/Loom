import { describe, expect, it } from "vitest";
import {
  buildReadingContextDisplay,
  contextGroupForKind,
  DEFAULT_CONTEXT_LIMITS,
  eventRoleLabel,
  type ContextDisplayItem,
  type ContextDisplayGroup,
} from "../src/lib/reading-context-display";
import type { ContextEntityView } from "../src/lib/reading-types";

function entity(overrides: Partial<ContextEntityView> = {}): ContextEntityView {
  return {
    entity_ref: overrides.entity_ref ?? `ref-${Math.random().toString(36).slice(2)}`,
    name: overrides.name ?? "无名",
    canonical_id: overrides.canonical_id ?? null,
    kind: overrides.kind ?? "person",
    importance: overrides.importance ?? "other",
    source_anchor_ids: overrides.source_anchor_ids ?? [],
    event_roles: overrides.event_roles ?? [],
  };
}

function group(display: ReturnType<typeof buildReadingContextDisplay>, key: string): ContextDisplayGroup {
  const found = display.groups.find((candidate) => candidate.key === key);
  if (!found) throw new Error(`missing group ${key}`);
  return found;
}

function names(items: readonly ContextDisplayItem[]): string[] {
  return items.map((item) => item.name);
}

describe("context group projection", () => {
  it("maps every published kind to the contract group without treating armies/polities as people", () => {
    expect(contextGroupForKind("person")).toBe("people");
    expect(contextGroupForKind("place")).toBe("places");
    expect(contextGroupForKind("polity")).toBe("polities");
    expect(contextGroupForKind("organization")).toBe("polities");
    expect(contextGroupForKind("army")).toBe("polities");
    expect(contextGroupForKind("office")).toBe("polities");
    expect(contextGroupForKind("group")).toBe("others");
    expect(contextGroupForKind("other")).toBe("others");
  });

  it("separates people, places, polities and other objects into their own groups", () => {
    const display = buildReadingContextDisplay([
      entity({ entity_ref: "p1", name: "周瑜", kind: "person" }),
      entity({ entity_ref: "pl1", name: "南郡", kind: "place" }),
      entity({ entity_ref: "g1", name: "吳", kind: "polity" }),
      entity({ entity_ref: "a1", name: "水軍", kind: "army" }),
      entity({ entity_ref: "o1", name: "某物", kind: "other" }),
    ]);
    expect(names(group(display, "people").items)).toEqual(["周瑜"]);
    expect(names(group(display, "places").items)).toEqual(["南郡"]);
    expect(names(group(display, "polities").items)).toEqual(["吳", "水軍"]);
    expect(names(group(display, "others").items)).toEqual(["某物"]);
  });

  it("orders primary items first then first-appearance order, stably", () => {
    const display = buildReadingContextDisplay([
      entity({ entity_ref: "a", name: "甲", importance: "other" }),
      entity({ entity_ref: "b", name: "乙", importance: "primary" }),
      entity({ entity_ref: "c", name: "丙", importance: "other" }),
      entity({ entity_ref: "d", name: "丁", importance: "primary" }),
    ]);
    expect(names(group(display, "people").items)).toEqual(["乙", "丁", "甲", "丙"]);
  });
});

describe("canonical dedup and source/role preservation", () => {
  it("merges entries that share a canonical ID but keeps every source anchor and event role", () => {
    const display = buildReadingContextDisplay([
      entity({
        entity_ref: "source-a",
        canonical_id: "ent-zhouyu",
        name: "周瑜",
        importance: "other",
        source_anchor_ids: ["anc-a"],
        event_roles: [{ event_ref: "evt-red-cliffs", role: "督", participant_index: 0 }],
      }),
      entity({
        entity_ref: "source-b",
        canonical_id: "ent-zhouyu",
        name: "周瑜",
        importance: "primary",
        source_anchor_ids: ["anc-b"],
        event_roles: [{ event_ref: "evt-nanjun", role: "領軍", participant_index: 1 }],
      }),
    ]);
    const [item] = group(display, "people").items;
    expect(display.totalItems).toBe(1);
    expect(item.deduped).toBe(true);
    expect(item.entityRefs).toEqual(["source-a", "source-b"]);
    expect(item.sourceAnchorIds).toEqual(["anc-a", "anc-b"]);
    expect(item.importance).toBe("primary");
    expect(item.roles.map((role) => `${role.eventRef}:${role.role}:${role.participantIndex}`)).toEqual([
      "evt-red-cliffs:督:0",
      "evt-nanjun:領軍:1",
    ]);
  });

  it("keeps same-name entities with different canonical IDs separate", () => {
    const display = buildReadingContextDisplay([
      entity({ entity_ref: "a", canonical_id: "ent-1", name: "張飛" }),
      entity({ entity_ref: "b", canonical_id: "ent-2", name: "張飛" }),
    ]);
    const people = group(display, "people");
    expect(people.items).toHaveLength(2);
    expect(new Set(people.items.map((item) => item.canonicalId))).toEqual(new Set(["ent-1", "ent-2"]));
  });

  it("does not merge unknown entities without a canonical ID", () => {
    const display = buildReadingContextDisplay([
      entity({ entity_ref: "unknown-1", canonical_id: null, name: "某人" }),
      entity({ entity_ref: "unknown-2", canonical_id: null, name: "某人" }),
    ]);
    expect(group(display, "people").items).toHaveLength(2);
  });

  it("marks deduped entries and keeps the name from the current publication", () => {
    const display = buildReadingContextDisplay([
      entity({ entity_ref: "a", canonical_id: "ent-x", name: "曹操", source_anchor_ids: ["anc-1"] }),
      entity({ entity_ref: "b", canonical_id: "ent-x", name: "曹公", source_anchor_ids: ["anc-2"] }),
    ]);
    const [item] = group(display, "people").items;
    expect(item.name).toBe("曹操");
    expect(item.deduped).toBe(true);
    expect(item.entityRefs).toEqual(["a", "b"]);
  });
});

describe("default limits and expansion", () => {
  const sevenPeople = Array.from({ length: 7 }, (_, index) =>
    entity({ entity_ref: `p${index}`, name: `人物${index}`, importance: index === 0 ? "primary" : "other" }),
  );
  const fivePlaces = Array.from({ length: 5 }, (_, index) =>
    entity({ entity_ref: `l${index}`, name: `地点${index}`, kind: "place" }),
  );

  it("shows at most 6 people and 4 places by default while reporting the true total", () => {
    const display = buildReadingContextDisplay([...sevenPeople, ...fivePlaces]);
    const people = group(display, "people");
    const places = group(display, "places");
    expect(DEFAULT_CONTEXT_LIMITS.people).toBe(6);
    expect(people.items).toHaveLength(6);
    expect(people.total).toBe(7);
    expect(people.hiddenCount).toBe(1);
    expect(people.limit).toBe(6);
    expect(places.items).toHaveLength(4);
    expect(places.total).toBe(5);
    expect(places.hiddenCount).toBe(1);
  });

  it("reveals every entry when the group is expanded", () => {
    const display = buildReadingContextDisplay([...sevenPeople, ...fivePlaces], {
      expanded: { people: true, places: true },
    });
    expect(group(display, "people").items).toHaveLength(7);
    expect(group(display, "people").hiddenCount).toBe(0);
    expect(group(display, "places").items).toHaveLength(5);
  });

  it("honours custom limits without changing the default contract", () => {
    const display = buildReadingContextDisplay(sevenPeople, { limits: { people: 2 } });
    expect(group(display, "people").items).toHaveLength(2);
    expect(group(display, "people").hiddenCount).toBe(5);
  });
});

describe("empty and unknown segments", () => {
  it("returns no groups for null, undefined or empty input instead of widening to a chapter", () => {
    for (const value of [null, undefined, []]) {
      const display = buildReadingContextDisplay(value);
      expect(display.hasAny).toBe(false);
      expect(display.totalItems).toBe(0);
      expect(display.groups).toEqual([]);
    }
  });

  it("keeps entities that original text supports even without a direct Claim or canonical ID", () => {
    const display = buildReadingContextDisplay([
      entity({ entity_ref: "support-only", canonical_id: null, name: "某將", source_anchor_ids: ["anc-9"] }),
    ]);
    const [item] = group(display, "people").items;
    expect(display.hasAny).toBe(true);
    expect(item.canonicalId).toBeNull();
    expect(item.sourceAnchorIds).toEqual(["anc-9"]);
  });
});

describe("event role labelling", () => {
  it("keeps the event association explicit so a role is not read as a standing office", () => {
    expect(eventRoleLabel({ eventRef: "evt-red-cliffs", role: "使者" })).toBe(
      "使者（事件：evt-red-cliffs）",
    );
  });

  it("uses a resolved event label when one is available", () => {
    expect(
      eventRoleLabel({ eventRef: "evt-red-cliffs", role: "督" }, (ref) =>
        ref === "evt-red-cliffs" ? "赤壁之戰" : null,
      ),
    ).toBe("督（事件：赤壁之戰）");
  });
});

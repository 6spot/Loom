import { describe, expect, it } from "vitest";
import {
  PERSON_STATE_CONTEXT_MAX_BYTES,
  PERSON_STATE_CONTEXT_MAX_ENTRIES,
  PersonStateContextCache,
  buildHistoryPhaseContext,
  historyPhaseContextKey,
} from "../src/hooks/usePersonStateContext";
import { personStatePhaseKey } from "../src/lib/queries";
import type { HistoryEntity, HistoryParagraph } from "../src/lib/history-api";

const version = "a".repeat(64);
const otherVersion = "b".repeat(64);
const paragraphId = `hp_${"c".repeat(24)}`;
const otherParagraphId = `hp_${"d".repeat(24)}`;

function entity(id: string, name: string, kind: HistoryEntity["kind"] = "person"): HistoryEntity {
  return {
    id,
    name,
    kind,
    importance: "primary",
    states: [
      { id: `psi_${"e".repeat(24)}`, label: "官职", value: "偏将军", certainty: "clear", reason: "" },
    ],
  };
}

function paragraph(overrides: Partial<HistoryParagraph> = {}): HistoryParagraph {
  return {
    id: paragraphId,
    ordinal: 0,
    phase_id: "ph_001",
    group_id: "g1",
    segments: [],
    entities: [entity("person-1", "周瑜"), entity("place-1", "南郡", "place")],
    ...overrides,
  };
}

describe("composite history phase context", () => {
  it("keys the phase context by version, paragraph and phase", () => {
    const key = historyPhaseContextKey({ version, paragraph_id: paragraphId, phase_id: "ph_001" });
    expect(key).toContain(version);
    expect(key).toContain(paragraphId);
    expect(key).toContain("ph_001");
    expect(personStatePhaseKey({ version, paragraph_id: paragraphId, phase_id: "ph_001" })).toEqual([
      "chronicle",
      "person-state",
      "phase",
      version,
      paragraphId,
      "ph_001",
    ]);
    expect(historyPhaseContextKey({ version, paragraph_id: paragraphId, phase_id: "ph_002" })).not.toBe(key);
    expect(historyPhaseContextKey({ version: otherVersion, paragraph_id: paragraphId, phase_id: "ph_001" })).not.toBe(key);
    expect(historyPhaseContextKey({ version, paragraph_id: otherParagraphId, phase_id: "ph_001" })).not.toBe(key);
  });

  it("projects the paragraph's compiled states without deriving certainty", () => {
    const context = buildHistoryPhaseContext(version, paragraph());
    expect(context.status).toBe("ready");
    expect(context.phaseId).toBe("ph_001");
    expect(Object.keys(context.stateFacts).sort()).toEqual(["person-1", "place-1"]);
    expect(context.stateFacts["person-1"]?.[0]).toMatchObject({ label: "官职", value: "偏将军", certainty: "clear" });
  });

  it("marks a paragraph with no entities as empty and clears prior context", () => {
    const filled = buildHistoryPhaseContext(version, paragraph());
    const empty = buildHistoryPhaseContext(version, paragraph({ id: otherParagraphId, phase_id: "ph_009", entities: [] }));
    expect(empty.status).toBe("empty");
    expect(empty.key).not.toBe(filled.key);
    expect(empty.entities).toEqual([]);
    expect(empty.stateFacts).toEqual({});
  });
});

describe("bounded person-state context cache", () => {
  it("evicts the least recently used entry past the entry bound", () => {
    const cache = new PersonStateContextCache(2, PERSON_STATE_CONTEXT_MAX_BYTES);
    const a = buildHistoryPhaseContext(version, paragraph({ id: paragraphId }));
    const b = buildHistoryPhaseContext(version, paragraph({ id: otherParagraphId, phase_id: "ph_002" }));
    const c = buildHistoryPhaseContext(otherVersion, paragraph({ id: paragraphId }));
    cache.set(a.key, a);
    cache.set(b.key, b);
    expect(cache.get(a.key)).not.toBeNull(); // refresh a's recency
    cache.set(c.key, c);
    expect(cache.get(b.key)).toBeNull();
    expect(cache.get(a.key)).not.toBeNull();
    expect(cache.get(c.key)).not.toBeNull();
    expect(cache.size).toBe(2);
  });

  it("keeps the default bound finite and under the documented budget", () => {
    expect(PERSON_STATE_CONTEXT_MAX_ENTRIES).toBe(100);
    expect(PERSON_STATE_CONTEXT_MAX_BYTES).toBe(2 * 1024 * 1024);
    const cache = new PersonStateContextCache(3, 1);
    for (let index = 0; index < 5; index += 1) {
      const value = buildHistoryPhaseContext(version, paragraph({ id: `hp_${index.toString().padStart(24, "0")}` }));
      cache.set(value.key, value);
    }
    expect(cache.size).toBe(1);
  });
});

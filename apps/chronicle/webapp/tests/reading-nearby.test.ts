import { describe, expect, it } from "vitest";
import { nearbyReadingEvents } from "../src/lib/reading-nearby";
import type { ReadingUnit } from "../src/lib/reading-types";

function unit(ordinal: number, event: string, relation = "current", status = "resolved"): ReadingUnit {
  return { unit_id: `unit-${ordinal}`, stream_id: "stream", catalog_sha: "pinned", ordinal,
    segments: [{ kind: "event", text: "同名事件", span: { target_event_id: event, relation, status } }],
  } as ReadingUnit;
}

describe("nearby anchors", () => {
  it("only locates confirmed occurrences; retrospective, ambiguous and future mentions are excluded", () => {
    const entries = nearbyReadingEvents([unit(1, "a", "retrospective"), unit(2, "b", "foreshadow"),
      unit(3, "c", "current", "ambiguous"), unit(4, "d")], 3);
    expect(entries.map((entry) => entry.eventId)).toEqual(["d"]);
    expect(entries[0].locator).toEqual({ stream_id: "stream", catalog_sha: "pinned", unit_id: "unit-4" });
  });
  it("retains distinct identities with the same display name and the nearest precise occurrence", () => {
    const units = [unit(0, "a"), unit(4, "b"), unit(5, "a"), unit(6, "c"), unit(15, "d")];
    expect(nearbyReadingEvents(units, 5, 3).map((entry) => [entry.eventId, entry.ordinal]))
      .toEqual([["b", 4], ["a", 5], ["c", 6]]);
    expect(units).toHaveLength(5); // selecting an entry never filters the loaded history.
  });
});

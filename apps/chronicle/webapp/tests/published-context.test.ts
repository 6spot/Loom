import { describe, expect, it } from "vitest";
import { withPublishedContext } from "../src/lib/routes";

describe("published navigation context", () => {
  it("preserves only fixed-version and reading-return fields", () => {
    expect(
      withPublishedContext(
        "/events/event-1#evidence",
        "?catalog=cat-1&version=ver-1&para=hp_1&phase=phase-1&return=token&q=曹操&year=208",
      ),
    ).toBe("/events/event-1?catalog=cat-1&version=ver-1&para=hp_1&phase=phase-1&return=token#evidence");
  });

  it("does not overwrite an explicit destination context", () => {
    expect(withPublishedContext("/search?q=event&version=destination", "?version=source&para=hp_1")).toBe(
      "/search?q=event&version=destination&para=hp_1",
    );
  });
});

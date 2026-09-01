import test from "node:test";
import assert from "node:assert/strict";

import { safeRouteFor } from "./route_safe.mjs";


test("malformed percent-encoded browser routes become not-found", () => {
  assert.deepEqual(safeRouteFor("/events/%ZZ"), { view: "not_found", id: null });
  assert.deepEqual(safeRouteFor("/entities/%E0%A4%A"), { view: "not_found", id: null });
});

test("valid encoded canonical path segments still route normally", () => {
  assert.deepEqual(safeRouteFor("/events/abc%20def"), { view: "event", id: "abc def" });
});

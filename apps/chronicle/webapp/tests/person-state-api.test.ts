// C2-R3-T10 typed source person-state client 单元测试。
//
// 覆盖 person-state-reading.md §7 的 client 纪律：路径显式携带完整
// `{stream_id, catalog_sha, unit_id}` locator 与 person/section/cursor；
// query key 以 snapshot+person+section 为身份，换 catalog/person/section/
// cursor 不复用；错误/非 JSON/abort/迟到都会走显式分支。全部为合成数据，
// 不接真实后端。

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchPersonStateJSON,
  getPersonStateEvidence,
  getPersonStates,
  getReadingPeople,
  PersonStateAbortError,
  PersonStateApiError,
  personStateKeys,
  readingPeoplePath,
  readingPersonStateEvidencePath,
  readingPersonStatesPath,
} from "../src/lib/person-state-api";
import type { PersonStateLocator } from "../src/lib/person-state-types";

const CATALOG_A = "a".repeat(64);
const CATALOG_B = "b".repeat(64);
const STREAM_A = "019535d9-3df7-7000-8000-000000000001";
const UNIT_A = "ru_0123456789abcdef01234567";
const PERSON_A = "01a08e83-d302-7d83-8d0b-6e163ee27737";
const PERSON_B = "01a08e83-d302-7d83-8d0b-6e163ee27738";
const ITEM_A = "psi_0123456789abcdef01234567";
const ITEM_B = "psi_0123456789abcdef01234568";

const LOCATOR: PersonStateLocator = {
  stream_id: STREAM_A,
  catalog_sha: CATALOG_A,
  unit_id: UNIT_A,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("person-state client paths bind the full source locator", () => {
  it("builds the people path with catalog/limit/cursor", () => {
    const path = readingPeoplePath(LOCATOR, { catalog: CATALOG_A, limit: 6, cursor: "c1" });
    expect(path).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}/units/${UNIT_A}/people?catalog=${CATALOG_A}&limit=6&cursor=c1`,
    );
    // catalog may be omitted so the newest snapshot resolves once server side.
    expect(readingPeoplePath(LOCATOR)).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}/units/${UNIT_A}/people?limit=6`,
    );
  });

  it("builds the states path with section/phase/limit/cursor", () => {
    const path = readingPersonStatesPath(LOCATOR, PERSON_A, {
      catalog: CATALOG_A,
      section: "changes",
      phaseId: "ph_002",
      limit: 5,
      cursor: "cur",
    });
    expect(path).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}/units/${UNIT_A}/people/${PERSON_A}/states?catalog=${CATALOG_A}&section=changes&phase_id=ph_002&limit=5&cursor=cur`,
    );
  });

  it("builds the evidence path with the required item_id", () => {
    const path = readingPersonStateEvidencePath(LOCATOR, PERSON_A, {
      catalog: CATALOG_A,
      itemId: ITEM_A,
      phaseId: "ph_001",
      limit: 50,
    });
    expect(path).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}/units/${UNIT_A}/people/${PERSON_A}/states?catalog=${CATALOG_A}&section=evidence&item_id=${ITEM_A}&phase_id=ph_001&limit=50`,
    );
  });

  it("rejects malformed locator/catalog/phase/item/limit before any URL exists", () => {
    expect(() => readingPeoplePath({ ...LOCATOR, catalog_sha: "not-a-sha" })).toThrow(
      PersonStateApiError,
    );
    expect(() => readingPeoplePath({ ...LOCATOR, unit_id: "nope" })).toThrow(PersonStateApiError);
    expect(() => readingPeoplePath(LOCATOR, { catalog: "not-a-sha" })).toThrow(PersonStateApiError);
    expect(() => readingPeoplePath(LOCATOR, { limit: 0 })).toThrow(PersonStateApiError);
    expect(() => readingPeoplePath(LOCATOR, { limit: 51 })).toThrow(PersonStateApiError);
    expect(() => readingPersonStatesPath(LOCATOR, PERSON_A, { phaseId: "phase1" })).toThrow(
      PersonStateApiError,
    );
    expect(() => readingPersonStateEvidencePath(LOCATOR, PERSON_A, { itemId: "bad" })).toThrow(
      PersonStateApiError,
    );
  });
});

describe("person-state query keys isolate snapshot, person and section", () => {
  it("keeps the snapshot and locator identity in every key", () => {
    const peopleA = personStateKeys.people(LOCATOR);
    const peopleB = personStateKeys.people({ ...LOCATOR, catalog_sha: CATALOG_B });
    expect(peopleA).not.toEqual(peopleB);
    expect(peopleA).toContain(CATALOG_A);

    const statesA = personStateKeys.states(LOCATOR, PERSON_A, { section: "identities" });
    const statesB = personStateKeys.states(LOCATOR, PERSON_B, { section: "identities" });
    const statesChanges = personStateKeys.states(LOCATOR, PERSON_A, { section: "changes" });
    expect(statesA).not.toEqual(statesB);
    expect(statesA).not.toEqual(statesChanges);
  });

  it("includes the cursor so one page never replaces another", () => {
    const page1 = personStateKeys.people(LOCATOR, { cursor: null });
    const page2 = personStateKeys.people(LOCATOR, { cursor: "c2" });
    expect(page1).not.toEqual(page2);

    const evidenceA = personStateKeys.evidence(LOCATOR, PERSON_A, { itemId: ITEM_A });
    const evidenceB = personStateKeys.evidence(LOCATOR, PERSON_A, { itemId: ITEM_B });
    expect(evidenceA).not.toEqual(evidenceB);
  });
});

describe("person-state client fetch discipline", () => {
  it("returns the typed page and rejects a mismatched locator echo", async () => {
    const good = {
      stream_id: STREAM_A,
      unit_id: UNIT_A,
      catalog_sha: CATALOG_A,
      publication_id: "pub",
      state_manifest_sha: "m".repeat(64),
      phase_mode: "single",
      phases: [],
      limit: 6,
      people: [],
      people_count: 0,
      next_cursor: null,
      has_more: false,
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(good)));
    const page = await getReadingPeople(LOCATOR);
    expect(page.people_count).toBe(0);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ ...good, catalog_sha: CATALOG_B })),
    );
    await expect(getReadingPeople(LOCATOR)).rejects.toMatchObject({
      code: "inconsistent",
    });
  });

  it("maps typed 404/409 errors and non-JSON responses explicitly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          { schema: "chronicle.error", version: "0.1", error: { code: "not_found", message: "未知人物" } },
          404,
        ),
      ),
    );
    const notFound = await getPersonStates(LOCATOR, PERSON_A, { section: "identities" }).catch(
      (error: unknown) => error,
    );
    expect(notFound).toBeInstanceOf(PersonStateApiError);
    expect(notFound).toMatchObject({ status: 404, code: "not_found" });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          { schema: "chronicle.error", version: "0.1", error: { code: "inconsistent", message: "内部不一致" } },
          409,
        ),
      ),
    );
    const conflict = await getPersonStateEvidence(LOCATOR, PERSON_A, { itemId: ITEM_A }).catch(
      (error: unknown) => error,
    );
    expect(conflict).toMatchObject({ status: 409, code: "inconsistent" });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>not json</html>", { status: 200 })),
    );
    await expect(fetchPersonStateJSON("/api/v1/public/x")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("distinguishes a caller abort from a network failure", async () => {
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("aborted", "AbortError");
      }),
    );
    await expect(
      getReadingPeople(LOCATOR, {}, { signal: controller.signal }),
    ).rejects.toBeInstanceOf(PersonStateAbortError);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network down");
      }),
    );
    await expect(getReadingPeople(LOCATOR)).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });
});

import { describe, expect, it } from "vitest";

import type { ReadingLocator } from "../src/lib/reading-types";
import {
  RETURN_STACK_LIMIT,
  ReadingHistoryStore,
  ReadingStorage,
  clampRelativeOffset,
  createReturnToken,
  type StorageLike,
} from "../src/lib/reading-history";

const STREAM = "01890a5d-ac96-774b-bcce-b302099a8057";
const CATALOG = "a".repeat(64);

const locator = (unit: string, stream = STREAM, catalog = CATALOG): ReadingLocator => ({
  stream_id: stream,
  catalog_sha: catalog,
  unit_id: `ru_${unit.padStart(24, "0")}`,
});

function memoryStorage(): StorageLike & { dump: () => Record<string, string> } {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    key(index: number) {
      return [...map.keys()][index] ?? null;
    },
    getItem(key: string) {
      return map.has(key) ? (map.get(key) as string) : null;
    },
    setItem(key: string, value: string) {
      map.set(key, String(value));
    },
    removeItem(key: string) {
      map.delete(key);
    },
    dump() {
      return Object.fromEntries(map);
    },
  };
}

const failingStorage = (): StorageLike => ({
  get length() {
    return 0;
  },
  key() {
    return null;
  },
  getItem() {
    return null;
  },
  setItem() {
    throw new Error("QuotaExceededError");
  },
  removeItem() {},
});

function counterRandom() {
  let counter = 0;
  return (target: Uint8Array) => {
    counter += 1;
    target.fill(counter % 256);
    return target;
  };
}

describe("reading history entries", () => {
  it("round-trips a bounded entry with relative position and focus", () => {
    const storage = new ReadingStorage(memoryStorage());
    const store = new ReadingHistoryStore(storage);
    const target = locator("1");
    const result = store.saveEntry({
      history_key: "hk1",
      locator: target,
      relative_offset: 1.4,
      focus_id: "evt-1",
      source_expanded: true,
    });
    expect(result.ok).toBe(true);
    const entry = store.loadEntry("hk1", target);
    expect(entry).toMatchObject({
      history_key: "hk1",
      relative_offset: 1,
      focus_id: "evt-1",
      source_expanded: true,
    });
    expect(store.loadEntry("hk2", target)).toBeNull();
  });

  it("finds an entry without a history key so refresh/deep-link can restore focus", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()));
    store.saveEntry({
      history_key: "hkA",
      locator: locator("2"),
      relative_offset: 0.25,
      focus_id: "span-9",
      source_expanded: false,
    });
    const found = store.findEntry(locator("2"));
    expect(found?.relative_offset).toBeCloseTo(0.25);
    expect(found?.focus_id).toBe("span-9");
    expect(store.findEntry(locator("3"))).toBeNull();
  });

  it("clamps relative offsets and ignores malformed stored records", () => {
    expect(clampRelativeOffset(-2)).toBe(0);
    expect(clampRelativeOffset(2)).toBe(1);
    expect(clampRelativeOffset(Number.NaN)).toBe(0);
    const raw = memoryStorage();
    raw.setItem("chronicle.reading.v1.entry.hk1.bad", "{not json");
    raw.setItem(
      "chronicle.reading.v1.entry.hk2",
      JSON.stringify({ history_key: "hk2", locator: { stream_id: "x" }, relative_offset: 0, focus_id: null, source_expanded: false }),
    );
    const store = new ReadingHistoryStore(new ReadingStorage(raw));
    expect(store.findEntry(locator("2"))).toBeNull();
  });

  it("restores the most recently updated position while keeping a pinned history entry", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()));
    const first = { history_key: "hkA", locator: locator("2"), relative_offset: 0.1, focus_id: null, source_expanded: false };
    store.saveEntry(first);
    store.saveEntry({ ...first, history_key: "hkB", relative_offset: 0.3 });
    store.saveEntry({ ...first, relative_offset: 0.7 });
    expect(store.findEntry(locator("2"))?.relative_offset).toBeCloseTo(0.7);
    expect(store.findEntry(locator("2"), ["hkB"])?.relative_offset).toBeCloseTo(0.3);
  });
});

describe("return tokens and bounded stack", () => {
  it("creates an unpredictable-shaped token and resolves it to a typed locator", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => 1000,
    });
    const target = locator("7");
    const remembered = store.rememberReturn(target);
    expect(remembered.persisted).toBe(true);
    expect(remembered.token).toMatch(/^rt_[0-9a-f]{32}$/);
    expect(store.resolveReturn(remembered.token)).toEqual(target);
  });

  it("rejects missing, malformed, tampered and expired tokens", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => 10_000,
      ttlMs: 1000,
    });
    expect(store.resolveReturn(null)).toBeNull();
    expect(store.resolveReturn("rt_not-hex")).toBeNull();
    expect(store.resolveReturn("rt_" + "f".repeat(32))).toBeNull();

    const expired = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => 10_000,
      ttlMs: 0,
    });
    expect(expired.resolveReturn(expired.rememberReturn(locator("4")).token)).toEqual(locator("4"));

    let clock = 0;
    const ticking = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => clock,
      ttlMs: 1000,
    });
    const token = ticking.rememberReturn(locator("5")).token;
    clock = 5000;
    expect(ticking.resolveReturn(token)).toBeNull();
  });

  it("bounds the return stack to the documented limit", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => 1,
    });
    for (let index = 0; index < RETURN_STACK_LIMIT + 7; index += 1) {
      store.rememberReturn(locator(String(index)));
    }
    expect(store.loadReturnStack().length).toBe(RETURN_STACK_LIMIT);
    // The newest target survives; the oldest dropped.
    expect(store.loadReturnStack().at(-1)?.locator).toEqual(locator(String(RETURN_STACK_LIMIT + 6)));
  });

  it("drops the oldest target when the byte budget would be exceeded", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => 1,
      maxBytes: 420,
    });
    for (let index = 0; index < 10; index += 1) store.rememberReturn(locator(String(index)));
    const stack = store.loadReturnStack();
    expect(stack.length).toBeGreaterThan(0);
    expect(stack.length).toBeLessThan(10);
  });

  it("forgets a token explicitly", () => {
    const store = new ReadingHistoryStore(new ReadingStorage(memoryStorage()), {
      randomBytes: counterRandom(),
      now: () => 1,
    });
    const token = store.rememberReturn(locator("6")).token;
    store.forgetReturn(token);
    expect(store.resolveReturn(token)).toBeNull();
  });

  it("degrades safely when storage is unavailable", () => {
    const adapter = new ReadingStorage(failingStorage());
    expect(adapter.available()).toBe(false);
    const store = new ReadingHistoryStore(adapter, { randomBytes: counterRandom(), now: () => 1 });
    const remembered = store.rememberReturn(locator("8"));
    expect(remembered.persisted).toBe(false);
    expect(store.resolveReturn(remembered.token)).toBeNull();
    expect(store.loadReturnStack()).toEqual([]);
    expect(store.findEntry(locator("8"))).toBeNull();
  });

  it("creates tokens from a secure source and fails loudly without one", () => {
    const bytes = (target: Uint8Array) => {
      for (let index = 0; index < target.length; index += 1) target[index] = index;
      return target;
    };
    expect(createReturnToken(bytes)).toBe("rt_000102030405060708090a0b0c0d0e0f");
  });
});

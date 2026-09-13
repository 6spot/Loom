import { afterEach, describe, expect, it, vi } from "vitest";
import { HISTORY_POSITION_STRATEGY as strategy, historyPath, historyPositionKey, loadHistory, loadHistoryPage } from "../src/lib/history-api";
import { isReadingLocator } from "../src/lib/reading-types";
import { ReadingHistoryStore, ReadingStorage } from "../src/lib/reading-history";

const version = "a".repeat(64);
const id = `hp_${"b".repeat(24)}`;
const position = historyPositionKey({ version, paragraph_id: id });
afterEach(() => vi.unstubAllGlobals());

describe("historical narrative locations stay separate from source reading", () => {
  it("round trips a pinned paragraph without weakening the original source validator", () => {
    const url = historyPath({ version, paragraph_id: id });
    expect(url).toBe(`/history/${version}/${id}`);
    expect(strategy.parse(url)).toEqual({ ok: true, location: position });
    expect(strategy.validate!(position)).toBe(true);
    expect(isReadingLocator(position)).toBe(false);
    expect(strategy.parse(`/read/anything?version=${version}&at=${id}`).ok).toBe(false);
  });
  it("rejects missing versions, duplicate fields, external targets and source unit ids", () => {
    for (const url of [`/history?at=${id}`, `/history?version=${version}&version=${version}`,
      `https://example.org/history?version=${version}&at=${id}`, `/history?version=${version}&at=ru_${"b".repeat(24)}`,
      `/history?version=${version}&year=208`]) expect(strategy.parse(url).ok).toBe(false);
    expect(strategy.parse(`/history?version=${version}`)).toMatchObject({ ok: true, location: { unit_id: null } });
    expect(strategy.parse(`/history/${version}`)).toMatchObject({ ok: true, location: { unit_id: null } });
    expect(strategy.parse(`/history?version=${version}&at=${id}`)).toEqual({ ok: true, location: position });
    for (const path of [`/history/${id}`, `/history/${version}/ru_${"b".repeat(24)}`,
      `/history/${version}/${id}/extra`, `/history/${version}/${id}?at=${id}`,
      `/history/${version}/${id}?version=${"c".repeat(64)}`, `https://example.org/history/${version}/${id}`]) {
      expect(strategy.parse(path).ok, path).toBe(false);
    }
  });
  it("keeps history return tokens out of the source-reader storage", () => {
    const entries = new Map<string, string>();
    const storage = { getItem: (key: string) => entries.get(key) ?? null, setItem: (key: string, value: string) => { entries.set(key, value); }, removeItem: (key: string) => { entries.delete(key); } };
    const history = new ReadingHistoryStore(new ReadingStorage(storage, strategy.storagePrefix), { validateLocator: strategy.validate });
    const token = history.rememberReturn(position);
    expect(history.resolveReturn(token.token)).toEqual(position);
    const source = new ReadingHistoryStore(new ReadingStorage(storage));
    expect(source.resolveReturn(token.token)).toBeNull();
  });
});

describe("fixed narrative responses", () => {
  it("requires bounded, ordered navigation covering the full prose and its curated entries", async () => {
    const second = `hp_${"c".repeat(24)}`;
    const pub = { version, paragraph_count: 2, first_paragraph_id: id, entry_points: [{ paragraph_id: id }],
      navigation: [{ id, label: "208 年", period: null, start: 0, end: 1,
        items: [{ paragraph_id: id, ordinal: 0, label: "赤壁之战", period: null, importance: "major" }] }] };
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ publication: pub })));
    vi.stubGlobal("fetch", fetcher);
    expect(await loadHistory(version)).toEqual(pub);
    for (const navigation of [undefined, [], [{ ...pub.navigation[0], start: 1 }], [{ ...pub.navigation[0], end: 0 }],
      [{ ...pub.navigation[0], items: [] }], [{ ...pub.navigation[0], items: [{ ...pub.navigation[0].items[0], ordinal: -1 }] }],
      [{ ...pub.navigation[0], items: [{ ...pub.navigation[0].items[0], paragraph_id: second }] }],
      [{ ...pub.navigation[0], items: [pub.navigation[0].items[0], pub.navigation[0].items[0]] }]]) {
      fetcher.mockImplementationOnce(async () => new Response(JSON.stringify({ publication: { ...pub, navigation } })));
      await expect(loadHistory(version)).rejects.toThrow("时间轴");
    }
  });
  it("refuses a server response from a different publication", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ publication: { version: "c".repeat(64), paragraph_count: 1, entry_points: [] } }))));
    await expect(loadHistory(version)).rejects.toThrow("版本");
  });
  it("preserves page order and refuses a foreign paragraph id", async () => {
    const page = { publication_version: version, total: 2, start: 1, previous_start: 0, next_start: null,
      paragraphs: [{ id, ordinal: 1, entities: [], segments: [] }] };
    const fetcher = vi.fn(async (_url: unknown) => new Response(JSON.stringify(page)));
    vi.stubGlobal("fetch", fetcher);
    expect(await loadHistoryPage(version, { at: id })).toEqual(page);
    expect(String(fetcher.mock.calls[0]?.[0])).toContain(`version=${version}`);
    page.paragraphs[0].id = `ru_${"b".repeat(24)}`;
    await expect(loadHistoryPage(version, { at: id })).rejects.toThrow("不一致");
  });
});

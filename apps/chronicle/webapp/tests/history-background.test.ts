import { afterEach, describe, expect, it, vi } from "vitest";
import {
  historyBackgroundImagePath,
  historyBackgroundMaskStyle,
  historyBackgroundPath,
  historyBackgroundAdjacentParagraphIds,
  historyBackgroundStyle,
  loadHistoryBackground,
  type HistoryBackground,
} from "../src/lib/history-background";

const version = "a".repeat(64);
const paragraph = `hp_${"b".repeat(24)}`;
const assetId = "00000000-0000-4000-8000-000000000101";

function background(overrides: Partial<HistoryBackground> = {}): HistoryBackground {
  return {
    binding_id: "00000000-0000-4000-8000-000000000103",
    edition_version: version,
    start_paragraph_id: paragraph,
    end_paragraph_id: paragraph,
    start_ordinal: 0,
    end_ordinal: 0,
    asset_id: assetId,
    asset_version_id: "00000000-0000-4000-8000-000000000102",
    asset_version: 1,
    display: { opacity: 0.35, position: { x: 0.5, y: 0.5 }, scale: 1, mask: null },
    status: "active",
    active: true,
    revision: 1,
    etag: '"binding-1"',
    image_href: `/api/v1/public/background-assets/${assetId}?version=${version}&paragraph_id=${paragraph}`,
    asset: {
      asset_id: assetId,
      asset_version_id: "00000000-0000-4000-8000-000000000102",
      version: 1,
      filename: "red-cliffs.png",
      media_type: "image/png",
      width: 4,
      height: 3,
    },
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("reader background boundary", () => {
  it("selects only the exact loaded neighbors of the shared active paragraph", () => {
    const ids = [0, 1, 2, 3].map((ordinal) => ({ id: `hp_${ordinal.toString(16).padStart(24, "0")}`, ordinal }));
    expect(historyBackgroundAdjacentParagraphIds(ids, ids[1].id)).toEqual([ids[0].id, ids[2].id]);
    // A missing ordinal is a window gap, not permission to prefetch a distant paragraph.
    expect(historyBackgroundAdjacentParagraphIds([ids[0], ids[1], ids[3]], ids[1].id)).toEqual([ids[0].id]);
    expect(historyBackgroundAdjacentParagraphIds(ids, "hp_ffffffffffffffffffffffff")).toEqual([]);
  });

  it("reads exactly the active binding for the fixed edition and paragraph", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ background: background() })));
    vi.stubGlobal("fetch", fetcher);
    const loaded = await loadHistoryBackground(version, paragraph);
    expect(loaded?.binding_id).toBe("00000000-0000-4000-8000-000000000103");
    expect(fetcher.mock.calls[0][0]).toBe(
      `/api/v1/public/backgrounds?version=${version}&paragraph_id=${paragraph}`,
    );
    expect(new URLSearchParams(historyBackgroundPath(version, paragraph)).get("paragraph_id")).toBe(paragraph);
  });

  it("falls back to paper for unbound, disabled, mismatched, missing and failed reads", async () => {
    const cases: Array<() => Response> = [
      () => new Response(JSON.stringify({ background: null })),                       // unbound paragraph
      () => new Response(JSON.stringify({ background: background({ active: false, status: "disabled" }) })), // disabled
      () => new Response(JSON.stringify({ background: background({ edition_version: "c".repeat(64) }) })),   // wrong edition
      () => new Response(JSON.stringify({ error: { code: "not_found" } }), { status: 404 }),                  // unknown paragraph
      () => new Response("not json", { status: 200 }),                                                       // invalid body
      () => { throw new TypeError("network down"); },                                                        // transport failure
    ];
    for (const reply of cases) {
      vi.stubGlobal("fetch", vi.fn(async () => reply()));
      expect(await loadHistoryBackground(version, paragraph)).toBeNull();
    }
  });

  it("uses the exact binding locator for image bytes and never invents one", () => {
    const binding = background();
    expect(historyBackgroundImagePath(binding, version, paragraph)).toBe(binding.image_href);
    const withoutHref = background({ image_href: undefined });
    expect(historyBackgroundImagePath(withoutHref, version, paragraph)).toBe(
      `/api/v1/public/background-assets/${assetId}?version=${version}&paragraph_id=${paragraph}`,
    );
    expect(historyBackgroundImagePath(background({ image_href: undefined, asset_id: "", asset: {} } as Partial<HistoryBackground>), version, paragraph)).toBeNull();
    expect(historyBackgroundImagePath(background({ image_href: "https://other.example/image.png" }), version, paragraph)).toBe(
      `/api/v1/public/background-assets/${assetId}?version=${version}&paragraph_id=${paragraph}`,
    );
  });

  it("renders the saved display settings with bounded reader-side limits", () => {
    const style = historyBackgroundStyle(
      { opacity: 0.42, position: { x: 0.63, y: 0.2 }, scale: 1.2, mask: null },
      true,
    );
    expect(style).toEqual({ opacity: 0.42, objectPosition: "63% 20%", transform: "scale(1.2)" });
    // A pending image stays invisible, and out-of-contract numbers cannot hide
    // the prose or fill the viewport with an unbounded scale.
    expect(historyBackgroundStyle(background().display, false).opacity).toBe(0);
    const clamped = historyBackgroundStyle(
      { opacity: 9, position: { x: -3, y: 7 }, scale: 99, mask: null },
      true,
    );
    expect(clamped).toEqual({ opacity: 1, objectPosition: "0% 100%", transform: "scale(4)" });
  });

  it("maps saved mask edges to the reader overlay", () => {
    expect(historyBackgroundMaskStyle({ shape: "rect", top: 0.12, right: 0.08, bottom: 0.12, left: 0.08 }))
      .toEqual({ top: "12%", right: "8%", bottom: "12%", left: "8%" });
    expect(historyBackgroundMaskStyle({ shape: "gradient" })).toEqual({ top: "0%", right: "0%", bottom: "0%", left: "0%" });
  });
});

import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import React from "react";
import {
  anchorsForBlock,
  canonicalTargetForRef,
  chapterDetailPath,
  chapterDirectoryPath,
  chapterReaderKeys,
  chapterSourcePath,
  ChapterReaderApiError,
  classifyChapterError,
  createStaleGuard,
  fetchChapterDetail,
  fetchChapterDirectory,
  fetchChapterSource,
  mergeDirectoryPages,
  refDisplayName,
  type ChapterDetailResponse,
  type ChapterDirectoryResponse,
  type ChapterSourceResponse,
} from "../src/lib/chapter-reader";
import { ChapterDetailView } from "../src/pages/public/ChapterPage";
import { ChapterIndexView } from "../src/pages/public/ChapterIndexPage";
import { SourcePageSegments } from "../src/components/ChapterSourceReference";
import chapterDetailFixture from "./fixtures/chapter-reader/chapter-detail.json";
import directoryFixture from "./fixtures/chapter-reader/directory.json";
import sourceWindowFixture from "./fixtures/chapter-reader/source-window.json";
import sourceChapterPage1 from "./fixtures/chapter-reader/source-chapter-page1.json";
import sourceChapterPage2 from "./fixtures/chapter-reader/source-chapter-page2.json";
import sourceMalicious from "./fixtures/chapter-reader/source-malicious.json";

const webappRoot = new URL("..", import.meta.url).pathname;
const PUB_A = "00000000-0000-7000-8000-000000000000";
const PUB_B = "11111111-1111-7000-8000-111111111111";
const ANCHOR = "anc_f00ff77e8922b3e5";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(handler: (path: string) => Response | Promise<Response>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      calls.push(path);
      return handler(path);
    }),
  );
  return calls;
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("chapter-reader request paths and query keys", () => {
  it("binds directory/chapter/source to publication, anchor, view and cursor", () => {
    expect(chapterDirectoryPath({ limit: 50 })).toBe("/api/v1/public/chapters?limit=50");
    expect(chapterDirectoryPath({ limit: 50, cursor: "c123" })).toContain("cursor=c123");
    expect(chapterDetailPath(PUB_A)).toBe(`/api/v1/public/chapters/${PUB_A}`);
    expect(chapterSourcePath(PUB_A, ANCHOR, { view: "window" })).toBe(
      `/api/v1/public/chapters/${PUB_A}/sources/${ANCHOR}?view=window`,
    );
    expect(chapterSourcePath(PUB_A, ANCHOR, { view: "chapter", cursor: "p2" })).toContain(
      "view=chapter",
    );
    expect(chapterSourcePath(PUB_A, ANCHOR, { view: "chapter", cursor: "p2" })).toContain(
      "cursor=p2",
    );
    // query keys 隔离：换 publication/anchor/view/cursor 任一即不同 key
    expect(chapterReaderKeys.chapter(PUB_A)).not.toEqual(chapterReaderKeys.chapter(PUB_B));
    expect(chapterReaderKeys.source(PUB_A, ANCHOR, { view: "window" })).not.toEqual(
      chapterReaderKeys.source(PUB_A, ANCHOR, { view: "chapter" }),
    );
    expect(chapterReaderKeys.source(PUB_A, ANCHOR, {})).not.toEqual(
      chapterReaderKeys.source(PUB_A, "other-anchor", {}),
    );
    expect(chapterReaderKeys.directory({ cursor: null })).not.toEqual(
      chapterReaderKeys.directory({ cursor: "c1" }),
    );
  });

  it("never falls back to document-latest and never guesses anchors", () => {
    expect(() => chapterDetailPath("")).toThrowError(ChapterReaderApiError);
    expect(() => chapterDetailPath("   ")).toThrowError(/publication_id/);
    expect(() => chapterSourcePath(PUB_A, "")).toThrowError(/anchor_id/);
    for (const path of [
      chapterDirectoryPath({}),
      chapterDetailPath(PUB_A),
      chapterSourcePath(PUB_A, ANCHOR, {}),
    ]) {
      expect(path.startsWith("/api/v1/public/chapters")).toBe(true);
      expect(path).not.toContain("document");
      expect(path).not.toContain("latest");
    }
    expect(anchorsForBlock({ block_id: "t", text: "x", source_block_ids: ["b_001"] })).toEqual([]);
  });
});

describe("chapter-reader frozen DTO conformance", () => {
  it("harness detail matches the T01 frozen public chapter texts", () => {
    const frozen = JSON.parse(
      readFileSync(
        `${webappRoot}../ingestion/fixtures/c2r1-contract/public-chapter-response-example.json`,
        "utf-8",
      ),
    );
    const detail = chapterDetailFixture as unknown as ChapterDetailResponse;
    expect(detail.translation_blocks.map((block) => block.text)).toEqual(
      frozen.translation_blocks.map((block: { text: string }) => block.text),
    );
    const artifact = JSON.parse(
      readFileSync(
        `${webappRoot}../ingestion/fixtures/c2r1-contract/artifact-accepted.json`,
        "utf-8",
      ),
    );
    const anchorIds = (artifact.anchors as Array<{ anchor_id: string }>).map((a) => a.anchor_id);
    expect(anchorIds).toContain(ANCHOR);
  });

  it("harness source window matches the T01 frozen public source segments", () => {
    const frozen = JSON.parse(
      readFileSync(
        `${webappRoot}../ingestion/fixtures/c2r1-contract/public-source-response-example.json`,
        "utf-8",
      ),
    );
    const window = sourceWindowFixture as unknown as ChapterSourceResponse;
    expect(window.segments).toEqual(frozen.segments);
    expect(window.anchor_id).toBe(frozen.anchor_id);
  });
});

describe("chapter-reader directory and full chapter", () => {
  it("fetches the directory and the complete ordered blocks including the claim-free paragraph", async () => {
    stubFetch((path) => {
      if (path.startsWith("/api/v1/public/chapters?")) return jsonResponse(directoryFixture);
      return jsonResponse(chapterDetailFixture);
    });
    const directory = await fetchChapterDirectory({ limit: 50 });
    expect(directory.items).toHaveLength(2);
    expect(directory.items.map((item) => item.publication_id)).toEqual([PUB_A, PUB_B]);
    const detail = await fetchChapterDetail(PUB_A);
    expect(detail.translation_blocks).toHaveLength(2);
    expect(detail.translation_blocks[1].text).toBe("其人聽聞後君王下令退兵。");
    expect(detail.translation_blocks[1].entity_refs ?? []).toEqual([]);
  });

  it("renders every paragraph single-column with the tail reachable and no dual columns", () => {
    const detail = chapterDetailFixture as unknown as ChapterDetailResponse;
    const html = renderToString(React.createElement(ChapterDetailView, { detail }));
    expect(html).toContain("建安十三年曹操屯兵江陵");
    expect(html).toContain("其人聽聞後君王下令退兵。");
    expect(html).toContain("chr-single-column");
    expect(html).toContain('data-blocks="2"');
    expect(html).not.toContain("chr-dual");
    expect(html).not.toContain("two-column");
    expect(html).not.toContain("逐句双栏");

    const longDetail: ChapterDetailResponse = {
      ...detail,
      translation_blocks: Array.from({ length: 60 }, (_, index) => ({
        block_id: `t_${String(index + 1).padStart(3, "0")}`,
        text: `第${index + 1}段正文-tail-marker-${index + 1}`,
        source_block_ids: [],
        source_anchor_ids: [],
        entity_refs: [],
        event_refs: [],
      })),
    };
    const longHtml = renderToString(React.createElement(ChapterDetailView, { detail: longDetail }));
    expect(longHtml).toContain("tail-marker-60");
    expect(longHtml.match(/data-test="chapter-paragraph"/g)).toHaveLength(60);
  });

  it("renders an explicit empty state instead of a summary posing as the full text", () => {
    const detail = {
      ...(chapterDetailFixture as unknown as ChapterDetailResponse),
      translation_blocks: [],
    };
    const html = renderToString(React.createElement(ChapterDetailView, { detail }));
    expect(html).toContain("chapter-empty");
    expect(html).toContain("不会用摘要或其他版本补齐");
  });
});

describe("chapter-reader references: multi-anchor and honest unknown refs", () => {
  it("offers one button per server-issued anchor and never fabricates canonical links", () => {
    const detail = chapterDetailFixture as unknown as ChapterDetailResponse;
    const html = renderToString(React.createElement(ChapterDetailView, { detail }));
    expect(html).toContain(`data-anchor="${ANCHOR}"`);
    expect(html).toContain("data-anchor=\"anc_58d6842876db1d38\"");
    expect(html).toContain("data-anchor=\"anc_b003_window\"");
    // “公”(ent_003) 无 canonical 目标：如实显示文本，不伪造 /entities/ent_003
    expect(html).toContain("chapter-entity-text");
    expect(html).not.toContain("/entities/ent_003");
    expect(html).not.toContain("/entities/ent_001");
    expect(html).not.toContain("/events/evt_001");
    expect(refDisplayName({ kind: "entity", ref: "ent_003" }, detail.references)).toBe("公");
    expect(canonicalTargetForRef({ kind: "entity", ref: "ent_003" }, detail.references)).toBeNull();
    expect(canonicalTargetForRef({ kind: "event", ref: "evt_001" }, detail.references)).toBeNull();
  });

  it("links only when the server provides an explicit canonical target", () => {
    const detail = chapterDetailFixture as unknown as ChapterDetailResponse;
    const withCanonical: ChapterDetailResponse = {
      ...detail,
      references: {
        entities: [{ ref: "ent_001", name: "曹操", canonical_id: "canonical-cao" }],
        events: [],
      },
    };
    expect(canonicalTargetForRef({ kind: "entity", ref: "ent_001" }, withCanonical.references)).toBe(
      "/entities/canonical-cao",
    );
    const html = renderToString(React.createElement(ChapterDetailView, { detail: withCanonical }));
    expect(html).toContain('href="/entities/canonical-cao"');
  });
});

describe("chapter-reader on-demand source: expansion, pagination, race, retry", () => {
  it("expands window to chapter and follows next_cursor pages", async () => {
    const calls = stubFetch((path) => {
      if (path.includes("view=chapter") && path.includes("cursor=chapter-cursor-p2")) {
        return jsonResponse(sourceChapterPage2);
      }
      if (path.includes("view=chapter")) return jsonResponse(sourceChapterPage1);
      return jsonResponse(sourceWindowFixture);
    });
    const window = await fetchChapterSource(PUB_A, ANCHOR, { view: "window" });
    expect(window.segments).toHaveLength(1);
    expect(window.has_more).toBe(false);
    const page1 = await fetchChapterSource(PUB_A, ANCHOR, { view: "chapter" });
    expect(page1.next_cursor).toBe("chapter-cursor-p2");
    const page2 = await fetchChapterSource(PUB_A, ANCHOR, {
      view: "chapter",
      cursor: page1.next_cursor,
    });
    expect(page2.segments[0].text).toContain("王命退兵");
    expect(page2.has_more).toBe(false);
    expect(calls.filter((path) => path.includes("/sources/"))).toHaveLength(3);
  });

  it("drops the stale response when two publications are switched quickly", async () => {
    let resolveA!: (value: Response) => void;
    let resolveB!: (value: Response) => void;
    stubFetch((path) => {
      if (path.includes(PUB_A)) return new Promise<Response>((resolve) => { resolveA = resolve; });
      return new Promise<Response>((resolve) => { resolveB = resolve; });
    });
    const guard = createStaleGuard();
    const applied: string[] = [];
    const tokenA = guard.next();
    const pendingA = fetchChapterDetail(PUB_A).then((detail) => {
      if (guard.isCurrent(tokenA)) applied.push(`A:${detail.publication_id}`);
    });
    const tokenB = guard.next();
    const pendingB = fetchChapterDetail(PUB_B).then((detail) => {
      if (guard.isCurrent(tokenB)) applied.push(`B:${detail.publication_id}`);
    });
    resolveB(jsonResponse({ ...chapterDetailFixture, publication_id: PUB_B }));
    await pendingB;
    resolveA(jsonResponse(chapterDetailFixture));
    await pendingA;
    expect(guard.isCurrent(tokenA)).toBe(false);
    expect(applied).toEqual([`B:${PUB_B}`]);
  });

  it("retries a failed source request while the chapter text stays intact", async () => {
    let attempts = 0;
    stubFetch((path) => {
      if (path.includes("/sources/")) {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse({ error: { code: "upstream_limited", message: "限流" } }, 503);
        }
        return jsonResponse(sourceWindowFixture);
      }
      return jsonResponse(chapterDetailFixture);
    });
    const first = await fetchChapterSource(PUB_A, ANCHOR, { view: "window" }).catch(
      (failure: unknown) => failure,
    );
    expect(first).toBeInstanceOf(ChapterReaderApiError);
    expect(classifyChapterError(first).kind).toBe("error");
    const retried = await fetchChapterSource(PUB_A, ANCHOR, { view: "window" });
    expect(retried.segments[0].text).toContain("曹操屯江陵");
    expect(attempts).toBe(2);
    const detail = await fetchChapterDetail(PUB_A);
    expect(detail.translation_blocks[0].text).toContain("周瑜");
  });

  it("classifies 404 distinctly from other failures", () => {
    expect(classifyChapterError(new ChapterReaderApiError(404, "not_found", "无此版本")).kind).toBe(
      "not_found",
    );
    expect(classifyChapterError(new ChapterReaderApiError(503, "x", "限流")).kind).toBe("error");
    expect(classifyChapterError(new Error("boom")).kind).toBe("error");
  });
});

describe("chapter-reader safe rendering", () => {
  it("renders hostile source HTML as inert text using server highlight segments", () => {
    const page = sourceMalicious as unknown as ChapterSourceResponse;
    const html = renderToString(React.createElement(SourcePageSegments, { page }));
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("&lt;img");
    expect(html).toContain("<mark");
    expect(html).toContain("曹操屯江陵");
  });

  it("shows the directory empty state explicitly", () => {
    const empty: ChapterDirectoryResponse = { items: [], next_cursor: null, has_more: false };
    const html = renderToString(React.createElement(ChapterIndexView, { data: empty }));
    expect(html).toContain("chapter-index-empty");
    expect(html).toContain("还没有已发布的篇章");
  });

  it("merges cursor pages without loss or duplication", async () => {
    stubFetch((path) => {
      if (path.includes("cursor=")) {
        return jsonResponse({
          items: [directoryFixture.items[1], directoryFixture.items[0]],
          next_cursor: null,
        });
      }
      return jsonResponse({ items: [directoryFixture.items[0]], next_cursor: "c2" });
    });
    const page1 = await fetchChapterDirectory({ limit: 50 });
    const page2 = await fetchChapterDirectory({ limit: 50, cursor: page1.next_cursor });
    const merged = mergeDirectoryPages(mergeDirectoryPages([], page1), page2);
    expect(merged.map((item) => item.publication_id)).toEqual([
      "00000000-0000-7000-8000-000000000000",
      "11111111-1111-7000-8000-111111111111",
    ]);
  });

  it("renders chapter navigation entries and a load-more affordance", () => {
    const selected: string[] = [];
    const html = renderToString(
      React.createElement(ChapterIndexView, {
        data: { ...(directoryFixture as unknown as ChapterDirectoryResponse), next_cursor: "c2" },
        onLoadMore: () => {},
        onSelectChapter: (publicationId: string) => { selected.push(publicationId); },
      }),
    );
    expect(html).toContain("chapter-index-open");
    expect(html).toContain("chapter-index-more-button");
    expect(html).toContain("读下一页");
  });
});

describe("chapter-reader ownership boundary", () => {
  it("stays out of App, routes and global styles so the build leaves dist alone", () => {
    const app = readFileSync(`${webappRoot}src/App.tsx`, "utf-8");
    const routes = readFileSync(`${webappRoot}src/lib/routes.ts`, "utf-8");
    for (const source of [app, routes]) {
      expect(source).not.toContain("chapter-reader");
      expect(source).not.toContain("ChapterPage");
      expect(source).not.toContain("ChapterIndexPage");
      expect(source).not.toContain("ChapterSourceReference");
    }
    const css = readFileSync(`${webappRoot}src/styles/chapter-reader.css`, "utf-8");
    expect(css).toContain(".chr-single-column");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media");
    expect(css).not.toMatch(/^(html|body|button|a|input|p|h1)\s*\{/m);
    const lib = readFileSync(`${webappRoot}src/lib/chapter-reader.ts`, "utf-8");
    expect(lib).not.toContain("chronicle.css");
    expect(lib).not.toContain("from \"../App\"");
  });
});

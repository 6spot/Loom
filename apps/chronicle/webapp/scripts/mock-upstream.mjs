// Canned published-history/source-locator responses for the real-browser
// verification script. The mock serves the Python sidecar's internal `/v0/*`
// paths so the Rust public proxy is exercised end to end.
import { createServer } from "node:http";

export const RED_CLIFFS = "01a05cd7-439d-7071-bf00-86c664886b06";
export const UNMAPPED_EVENT = "01a05cd7-6666-7888-8999-000011112222";
export const CAO_CAO = "01a05cd7-1111-7222-8333-444455556666";
export const RED_CLIFFS_PLACE = "01a05cd7-3333-7444-8555-666677778888";
export const HISTORY_VERSION = "a".repeat(64);
export const READING_CATALOG = "c".repeat(64);
export const HISTORY_PARAGRAPH = `hp_${"1".repeat(24)}`;
export const READING_STREAM = "01a05cd7-5555-7666-8777-888899990000";
export const READING_UNIT = `ru_${"2".repeat(24)}`;

const HISTORY_PUBLICATION = {
  version: HISTORY_VERSION,
  catalog_sha: READING_CATALOG,
  title: "合成历史测试版",
  paragraph_count: 1,
  first_paragraph_id: HISTORY_PARAGRAPH,
  groups: [{ id: "history-group-1", year: 208, period: null, label: "建安十三年", first_paragraph_id: HISTORY_PARAGRAPH, count: 1 }],
  entry_points: [{ label: "赤壁之战", kind: "event", paragraph_id: HISTORY_PARAGRAPH, event_id: RED_CLIFFS, ordinal: 0, year: 208, period: null, excerpt: "测试正文入口；不是历史验收材料。" }],
  navigation: [{
    id: HISTORY_PARAGRAPH,
    label: "公元 208 年",
    period: null,
    start: 0,
    end: 0,
    items: [{ paragraph_id: HISTORY_PARAGRAPH, ordinal: 0, label: "赤壁之战", period: null, importance: "major" }],
  }],
};

const HISTORY_PAGE = {
  publication_version: HISTORY_VERSION,
  paragraphs: [{
    id: HISTORY_PARAGRAPH,
    ordinal: 0,
    phase_id: "history-phase-1",
    group_id: "history-group-1",
    segments: [{ text: "合成正文中的赤壁之战。", conclusion_ids: [], certainty: "clear", event_id: RED_CLIFFS, event_relation: "current", event_text: "赤壁之战" }],
    entities: [{ id: CAO_CAO, name: "曹操", kind: "person", importance: "primary", states: [] }],
  }],
  start: 0,
  total: 1,
  previous_start: null,
  next_start: null,
};

const EVENT_PREVIEW = {
  event_id: RED_CLIFFS,
  catalog_sha: READING_CATALOG,
  name: "赤壁之战",
  sources: [
    {
      source_title: "三国志·魏书·武帝纪",
      publication_id: "publication-wudi",
      observations: [{ original_text: "建安十三年", normalized: null, precision: "year" }],
      excerpt: "公至赤壁，与备战，不利。",
      excerpt_more: false,
      original_entry: { publication_id: "publication-wudi", anchor_id: "anchor-wudi" },
    },
    {
      source_title: "三国志·吴书·吴主传",
      publication_id: "publication-wuzhu",
      observations: [{ original_text: "建安十三年", normalized: null, precision: "year" }],
      excerpt: "遇于赤壁，大破曹公军。",
      excerpt_more: false,
      original_entry: { publication_id: "publication-wuzhu", anchor_id: "anchor-wuzhu" },
    },
  ],
  source_count: 2,
  has_more_sources: false,
};

const EVENT_TARGETS = {
  event_id: RED_CLIFFS,
  catalog_sha: READING_CATALOG,
  targets: [{
    event_id: RED_CLIFFS,
    catalog_sha: READING_CATALOG,
    relation: "current",
    stream_id: READING_STREAM,
    publication_id: "publication-wudi",
    chapter_id: "chapter-wudi",
    chapter_title: "武帝纪",
    source_title: "三国志·魏书·武帝纪",
    unit_id: READING_UNIT,
    span_id: "span-red-cliffs",
    locator: { stream_id: READING_STREAM, catalog_sha: READING_CATALOG, unit_id: READING_UNIT },
    excerpt: "公至赤壁，与备战，不利。",
  }],
  current_count: 1,
  mention_count: 0,
  next_cursor: null,
  has_more: false,
};

const CAO_ENTITY = {
  schema: "chronicle.entity-detail",
  version: "0.1",
  canonical_entity_id: CAO_CAO,
  display: { name: "曹操", type: "person" },
  source_count: 2,
  representation_count: 2,
  representations: [],
  events: [{ canonical_event_id: RED_CLIFFS, display: { title: "赤壁之战" }, time: { start_year: 208, end_year: 208 }, source_involvements: [{ participant_roles: ["commander"], as_place: false }] }],
  claims: [],
  resolution_links: [],
};

const PLACE_ENTITY = {
  schema: "chronicle.entity-detail",
  version: "0.1",
  canonical_entity_id: RED_CLIFFS_PLACE,
  display: { name: "赤壁", type: "place" },
  source_count: 1,
  representation_count: 1,
  representations: [],
  events: [{ canonical_event_id: RED_CLIFFS, display: { title: "赤壁之战" }, time: { start_year: 208, end_year: 208 }, source_involvements: [{ participant_roles: [], as_place: true }] }],
  claims: [],
  resolution_links: [{ decision: "uncertain", confidence: 0.55, rationale: "测试身份不确定" }],
};

function searchItems(q) {
  if (q.includes("曹操")) {
    return [{ kind: "entity", canonical_id: CAO_CAO, display: { name: "曹操", type: "person" }, representation_count: 2, source_count: 2, identity_uncertain: false, navigation_path: `/entities/${CAO_CAO}`, match: { rank: 0, matched_surfaces: [{ match: "exact", field: "entity.canonical_name", value: "曹操", source_title: "三国志·魏书·武帝纪" }] } }];
  }
  if (q.includes("赤壁")) {
    return [
      { kind: "event", canonical_id: RED_CLIFFS, display: { title: "赤壁之战", type: "battle" }, representation_count: 2, source_count: 2, navigation_path: `/events/${RED_CLIFFS}`, match: { rank: 0, matched_surfaces: [{ match: "exact", field: "event.title", value: "赤壁之战", source_title: "三国志·魏书·武帝纪" }] } },
      { kind: "entity", canonical_id: RED_CLIFFS_PLACE, display: { name: "赤壁", type: "place" }, representation_count: 1, source_count: 1, identity_uncertain: true, navigation_path: `/entities/${RED_CLIFFS_PLACE}`, match: { rank: 3, matched_surfaces: [{ match: "exact", field: "entity.canonical_name", value: "赤壁", source_title: "三国志·魏书·武帝纪" }] } },
    ];
  }
  if (q.includes("无正文")) {
    return [{ kind: "event", canonical_id: UNMAPPED_EVENT, display: { title: "无正文对应事件", type: "event" }, representation_count: 1, source_count: 1, navigation_path: `/events/${UNMAPPED_EVENT}`, match: { rank: 0, matched_surfaces: [{ match: "exact", field: "event.title", value: "无正文对应事件", source_title: "测试来源" }] } }];
  }
  return [];
}

function payloadFor(path, query) {
  if (path === "/v0/history") return [200, { publication: HISTORY_PUBLICATION }];
  if (path === "/v0/history/paragraphs") return [200, HISTORY_PAGE];
  if (path === "/v0/reading-streams") return [200, { schema: "chronicle.reading", version: "0.1", snapshot: { catalog_sha: READING_CATALOG, publication_sequence: 1 }, query: {}, page: { streams: [], limit: 1, has_more: false, next_cursor: null } }];
  if (path === `/v0/reading-events/${RED_CLIFFS}/preview`) return [200, EVENT_PREVIEW];
  if (path === `/v0/reading-events/${RED_CLIFFS}/targets`) return [200, EVENT_TARGETS];
  if (path === "/v0/search") {
    const items = searchItems(query.get("q") ?? "");
    return [200, { schema: "chronicle.search", version: "0.1", query: { q: query.get("q") ?? "", kind: query.get("kind") ?? "all", limit: 20 }, page: { total: items.length, returned: items.length, has_more: false }, items }];
  }
  if (path === `/v0/entities/${CAO_CAO}`) return [200, CAO_ENTITY];
  if (path === `/v0/entities/${RED_CLIFFS_PLACE}`) return [200, PLACE_ENTITY];
  if (path === `/v0/entities/${CAO_CAO}/history`) return [200, { person_id: CAO_CAO, publication: null, status: "empty", empty: true }];
  if (path.startsWith("/v0/chapters/") && path.includes("/sources/")) {
    return [200, { anchor_id: path.split("/sources/")[1], view: query.get("view") ?? "window", source_sha256: "d".repeat(64), chapter_range: [0, 1], page_range: [0, 1], segments: [{ text: "合成原文依据。", highlight: true }], next_cursor: null, has_more: false }];
  }
  return [404, { schema: "chronicle.error", version: "0.1", error: { code: "not_found", message: "mock: unknown path" } }];
}

export function startMockUpstream(port = 0) {
  const server = createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://127.0.0.1");
    const [status, payload] = payloadFor(url.pathname, url.searchParams);
    const body = JSON.stringify(payload);
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Content-Length": Buffer.byteLength(body) });
    res.end(body);
  });
  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => {
      const address = server.address();
      const actual = typeof address === "object" && address ? address.port : port;
      resolve({ server, port: actual, close: () => new Promise((done) => server.close(() => done())) });
    });
  });
}

// Canned C0-shaped Chronicle read-model responses for headless verification
// (Playwright visual checks and the React dev loop). Shapes mirror the C0
// read contracts; the mock serves /v0/* exactly like the Python sidecar so
// the Rust server proxy path is exercised end to end.
import { createServer } from "node:http";

export const RED_CLIFFS = "01a05cd7-439d-7071-bf00-86c664886b06";
export const CAO_CAO = "01a05cd7-1111-7222-8333-444455556666";
export const JIANGLING = "01a05cd7-2222-7333-8444-555566667777";
export const RED_CLIFFS_PLACE = "01a05cd7-3333-7444-8555-666677778888";
export const OTHER_RED_CLIFFS_PLACE = "01a05cd7-4444-7555-8666-777788889999";

const TIMELINE_ITEM = {
  canonical_event_id: RED_CLIFFS,
  display: { title: "赤壁之战", type: "battle" },
  time: { start_year: 208, end_year: 208, status: "single_year" },
  representation_count: 2,
  source_count: 2,
  source_titles: ["三国志·魏书·武帝纪", "三国志·吴书·吴主传"],
};

const EVENT_DETAIL = {
  schema: "chronicle.event-detail",
  version: "0.1",
  canonical_event_id: RED_CLIFFS,
  display: { title: "赤壁之战", type: "battle" },
  time: { start_year: 208, end_year: 208, status: "single_year" },
  source_count: 2,
  representations: [
    {
      bundle: "wudi",
      ref: "evt_022",
      source: { title: "三国志·魏书·武帝纪", record: { ref: "src_001" } },
      event: { title: "公至赤壁，与备战，不利" },
      claims: [
        {
          bundle: "wudi",
          ref: "clm_024",
          claim: {
            predicate: "outcome",
            evidence: { text: "公至赤壁，与备战，不利。", locator: { section: "建安十三年" } },
          },
        },
      ],
    },
    {
      bundle: "wuzhu",
      ref: "evt_016",
      source: { title: "三国志·吴书·吴主传", record: { ref: "src_002" } },
      event: { title: "瑜、普为左右督，各领万人，与备俱进，遇于赤壁，大破曹公军" },
      claims: [
        {
          bundle: "wuzhu",
          ref: "clm_018",
          claim: { predicate: "outcome", evidence: { text: "遇于赤壁，大破曹公军。", locator: {} } },
        },
      ],
    },
  ],
  participants: [
    {
      canonical_entity_id: CAO_CAO,
      display: { name: "曹操", type: "person" },
      source_roles: [{ bundle: "wudi", event_ref: "evt_022", entity_ref: "ent_001", role: "commander" }],
    },
  ],
  places: [
    {
      canonical_entity_id: RED_CLIFFS_PLACE,
      display: { name: "赤壁", type: "place" },
      source_refs: [{ bundle: "wudi", event_ref: "evt_022", entity_ref: "ent_010" }],
    },
  ],
  related_events: [
    {
      type: "related_occurrence",
      event: {
        canonical_event_id: JIANGLING,
        display: { title: "曹操北还并留军守江陵、襄阳", type: "military" },
        time: { start_year: 208, end_year: 208, status: "single_year" },
      },
      provenance: [],
    },
  ],
  resolution_links: [
    {
      candidate_id: "vc_001",
      decision: "same_occurrence",
      confidence: 0.98,
      rationale: "两来源描述同一赤壁交战。",
      signals: { time: "208" },
      left: { canonical_event_id: RED_CLIFFS },
      right: { canonical_event_id: RED_CLIFFS },
    },
  ],
};

const CAO_ENTITY = {
  schema: "chronicle.entity-detail",
  version: "0.1",
  canonical_entity_id: CAO_CAO,
  display: { name: "曹操", type: "person" },
  source_count: 2,
  representation_count: 2,
  representations: [
    {
      bundle: "wudi",
      ref: "ent_001",
      source: { title: "三国志·魏书·武帝纪", record: {} },
      entity: { canonical_name: "曹操", aliases: ["曹孟德"] },
      claims: [],
    },
    {
      bundle: "wuzhu",
      ref: "ent_004",
      source: { title: "三国志·吴书·吴主传", record: {} },
      entity: { canonical_name: "曹操", aliases: ["曹公"] },
      claims: [],
    },
  ],
  events: [
    {
      canonical_event_id: RED_CLIFFS,
      display: { title: "赤壁之战", type: "battle" },
      time: { start_year: 208, end_year: 208, status: "single_year" },
      source_involvements: [
        { bundle: "wudi", entity_ref: "ent_001", event_ref: "evt_022", participant_roles: ["commander"], as_place: false },
      ],
    },
  ],
  claims: [],
  resolution_links: [
    {
      candidate_id: "vc_002",
      decision: "same_entity",
      confidence: 0.99,
      rationale: "两来源指向同一人物曹操。",
      signals: { name: "曹操" },
      left: { canonical_entity_id: CAO_CAO },
      right: { canonical_entity_id: CAO_CAO },
    },
  ],
};

const PLACE_ENTITY = {
  schema: "chronicle.entity-detail",
  version: "0.1",
  canonical_entity_id: RED_CLIFFS_PLACE,
  display: { name: "赤壁", type: "place" },
  representation_count: 1,
  source_count: 1,
  representations: [
    {
      bundle: "wudi",
      ref: "ent_010",
      source: { title: "三国志·魏书·武帝纪", record: {} },
      entity: { canonical_name: "赤壁", aliases: [] },
      claims: [],
    },
  ],
  events: [
    {
      canonical_event_id: RED_CLIFFS,
      display: { title: "赤壁之战", type: "battle" },
      time: { start_year: 208, end_year: 208, status: "single_year" },
      source_involvements: [
        { bundle: "wudi", entity_ref: "ent_010", event_ref: "evt_022", participant_roles: [], as_place: true },
      ],
    },
  ],
  claims: [],
  resolution_links: [
    {
      candidate_id: "vc_010",
      decision: "uncertain",
      confidence: 0.55,
      rationale: "同名地点但现有来源不足以证明身份完全相同。",
      signals: { name: "赤壁" },
      left: { canonical_entity_id: RED_CLIFFS_PLACE },
      right: { canonical_entity_id: OTHER_RED_CLIFFS_PLACE },
    },
  ],
};

function searchItems(q) {
  if (q.includes("曹操")) {
    return [
      {
        kind: "entity",
        canonical_id: CAO_CAO,
        display: { name: "曹操", type: "person" },
        representation_count: 2,
        source_count: 2,
        source_titles: ["三国志·魏书·武帝纪", "三国志·吴书·吴主传"],
        identity_uncertain: false,
        navigation_path: `/entities/${CAO_CAO}`,
        match: {
          rank: 0,
          matched_surfaces: [
            { rank: 1, match: "exact", field: "entity.canonical_name", value: "曹操", bundle: "wudi", ref: "ent_001", source_title: "三国志·魏书·武帝纪" },
            { rank: 2, match: "exact", field: "entity.canonical_name", value: "曹操", bundle: "wuzhu", ref: "ent_004", source_title: "三国志·吴书·吴主传" },
          ],
        },
      },
    ];
  }
  if (q.includes("赤壁")) {
    return [
      {
        kind: "event",
        canonical_id: RED_CLIFFS,
        display: { title: "赤壁之战", type: "battle" },
        time: { start_year: 208, end_year: 208, status: "single_year" },
        representation_count: 2,
        source_count: 2,
        source_titles: ["三国志·魏书·武帝纪", "三国志·吴书·吴主传"],
        navigation_path: `/events/${RED_CLIFFS}`,
        match: {
          rank: 0,
          matched_surfaces: [
            { rank: 1, match: "exact", field: "event.title", value: "赤壁之战", bundle: "wudi", ref: "evt_022", source_title: "三国志·魏书·武帝纪" },
          ],
        },
      },
      {
        kind: "entity",
        canonical_id: RED_CLIFFS_PLACE,
        display: { name: "赤壁", type: "place" },
        representation_count: 1,
        source_count: 1,
        source_titles: ["三国志·魏书·武帝纪"],
        identity_uncertain: true,
        navigation_path: `/entities/${RED_CLIFFS_PLACE}`,
        match: {
          rank: 3,
          matched_surfaces: [
            { rank: 3, match: "exact", field: "entity.canonical_name", value: "赤壁", bundle: "wudi", ref: "ent_010", source_title: "三国志·魏书·武帝纪" },
          ],
        },
      },
    ];
  }
  return [];
}

function payloadFor(path, query) {
  if (path === "/healthz") return [200, { status: "ok" }];
  if (path === "/v0/timeline") {
    return [
      200,
      {
        schema: "chronicle.timeline",
        version: "0.1",
        query: { from_year: 208, to_year: 208, limit: 50, offset: 0 },
        page: { total: 1, returned: 1, has_more: false },
        items: [TIMELINE_ITEM],
      },
    ];
  }
  if (path === "/v0/search") {
    const q = query.get("q") ?? "";
    const items = searchItems(q);
    return [
      200,
      {
        schema: "chronicle.search",
        version: "0.1",
        query: { q, kind: query.get("kind") ?? "all", limit: 20 },
        page: { total: items.length, returned: items.length, has_more: false },
        items,
      },
    ];
  }
  if (path === `/v0/events/${RED_CLIFFS}`) return [200, EVENT_DETAIL];
  if (path === `/v0/entities/${CAO_CAO}`) return [200, CAO_ENTITY];
  if (path === `/v0/entities/${RED_CLIFFS_PLACE}`) return [200, PLACE_ENTITY];
  return [404, { schema: "chronicle.error", version: "0.1", error: { code: "not_found", message: "mock: unknown id" } }];
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

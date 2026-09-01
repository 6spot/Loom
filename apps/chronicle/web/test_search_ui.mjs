import assert from "node:assert/strict";
import test from "node:test";

import { safeRouteFor } from "./route_safe.mjs";
import { renderSearch, renderSearchEmpty, searchApiPath } from "./search_ui.mjs";

const ENTITY_ID = "01a05cd7-439d-7172-b459-8d0c0747f5f2";
const EVENT_ID = "01a05cd7-439d-7071-bf00-86c664886b06";

function payload() {
  return {
    schema: "chronicle.search",
    version: "0.1",
    query: { q: "赤壁", kind: "all", limit: 20 },
    page: { total: 2, returned: 2, has_more: false },
    items: [
      {
        kind: "entity",
        canonical_id: ENTITY_ID,
        display: { name: "赤壁", type: "place" },
        representation_count: 1,
        source_count: 1,
        source_titles: ["三国志·魏书·武帝纪"],
        identity_uncertain: true,
        navigation_path: `/entities/${ENTITY_ID}`,
        match: {
          rank: 0,
          matched_surfaces: [
            {
              rank: 1,
              match: "exact",
              field: "entity.canonical_name",
              value: "赤壁",
              bundle: "wudi",
              ref: "ent_009",
              source_title: "三国志·魏书·武帝纪",
            },
          ],
        },
      },
      {
        kind: "event",
        canonical_id: EVENT_ID,
        display: { title: "赤壁之战", type: "battle" },
        time: { start_year: 208, end_year: 208, status: "single_year" },
        representation_count: 2,
        source_count: 2,
        source_titles: ["三国志·魏书·武帝纪", "三国志·吴书·吴主传"],
        navigation_path: `/events/${EVENT_ID}`,
        match: {
          rank: 3,
          matched_surfaces: [
            {
              rank: 3,
              match: "substring",
              field: "event.title",
              value: "赤壁之战",
              bundle: "wudi",
              ref: "evt_010",
              source_title: "三国志·魏书·武帝纪",
            },
          ],
        },
      },
    ],
  };
}

test("search route is a first-class browser view", () => {
  assert.deepEqual(safeRouteFor("/search"), { view: "search", id: null });
  assert.deepEqual(safeRouteFor("/search/"), { view: "search", id: null });
});

test("search API path forwards only search contract parameters", () => {
  assert.equal(
    searchApiPath("?q=%E8%B5%A4%E5%A3%81&kind=event&limit=5&database_url=forbidden"),
    "/v0/search?q=%E8%B5%A4%E5%A3%81&kind=event&limit=5",
  );
});

test("mixed search results link to existing canonical Event and Entity routes", () => {
  const html = renderSearch(payload());
  assert.match(html, /data-view="search"/);
  assert.match(html, new RegExp(`/entities/${ENTITY_ID}`));
  assert.match(html, new RegExp(`/events/${EVENT_ID}`));
  assert.match(html, /身份不确定/);
  assert.match(html, /为什么命中/);
  assert.match(html, /三国志·魏书·武帝纪/);
  assert.match(html, /公元 208 年/);
});

test("search rendering escapes dynamic source surfaces", () => {
  const data = payload();
  data.items[0].match.matched_surfaces[0].value = '<img src=x onerror="boom">';
  const html = renderSearch(data);
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x onerror=&quot;boom&quot;&gt;/);
});

test("empty search state is explicit and remains source-grounded", () => {
  const html = renderSearchEmpty();
  assert.match(html, /搜索历史世界/);
  assert.match(html, /词面检索/);
  assert.match(html, /不会用模型生成一个看似权威的历史答案/);
});

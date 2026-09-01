import test from "node:test";
import assert from "node:assert/strict";

import {
  escapeHTML,
  renderEntity,
  renderEvent,
  renderTimeline,
  routeFor,
  timelineApiPath,
} from "./ui.mjs";

const RED_CLIFFS = "01a05cd7-439d-7071-bf00-86c664886b06";
const CAO_CAO = "01a05cd7-1111-7222-8333-444455556666";
const JIANGLING = "01a05cd7-2222-7333-8444-555566667777";
const RED_CLIFFS_PLACE = "01a05cd7-3333-7444-8555-666677778888";
const OTHER_RED_CLIFFS_PLACE = "01a05cd7-4444-7555-8666-777788889999";

function occurrences(text, needle) {
  return text.split(needle).length - 1;
}

test("routing stays on canonical Timeline/Event/Entity URLs", () => {
  assert.deepEqual(routeFor("/"), { view: "timeline", id: null });
  assert.deepEqual(routeFor("/timeline/"), { view: "timeline", id: null });
  assert.deepEqual(routeFor(`/events/${RED_CLIFFS}`), { view: "event", id: RED_CLIFFS });
  assert.deepEqual(routeFor(`/entities/${CAO_CAO}`), { view: "entity", id: CAO_CAO });
  assert.deepEqual(routeFor("/unknown"), { view: "not_found", id: null });
  assert.equal(timelineApiPath("?from_year=208&to_year=208"), "/v0/timeline?from_year=208&to_year=208&limit=50&offset=0");
});

test("Timeline renders one canonical Red Cliffs card backed by both sources", () => {
  const html = renderTimeline({
    schema: "chronicle.timeline",
    version: "0.1",
    query: { from_year: 208, to_year: 208, limit: 50, offset: 0 },
    page: { total: 1, returned: 1, has_more: false },
    items: [{
      canonical_event_id: RED_CLIFFS,
      display: { title: "赤壁之战", type: "battle" },
      time: { start_year: 208, end_year: 208, status: "single_year" },
      representation_count: 2,
      source_count: 2,
      source_titles: ["三国志·魏书·武帝纪", "三国志·吴书·吴主传"],
    }],
  });

  assert.equal(occurrences(html, `data-event-id="${RED_CLIFFS}"`), 1);
  assert.equal(occurrences(html, ">赤壁之战</a>"), 1);
  assert.match(html, /公元 208 年/);
  assert.match(html, /2 个来源/);
  assert.match(html, /三国志·魏书·武帝纪/);
  assert.match(html, /三国志·吴书·吴主传/);
  assert.match(html, new RegExp(`/events/${RED_CLIFFS}`));
});

test("Event Detail keeps source evidence separate and related events distinct", () => {
  const html = renderEvent({
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
        claims: [{
          bundle: "wudi",
          ref: "clm_024",
          claim: { predicate: "outcome", evidence: { text: "公至赤壁，与备战，不利。", locator: { section: "建安十三年" } } },
        }],
      },
      {
        bundle: "wuzhu",
        ref: "evt_016",
        source: { title: "三国志·吴书·吴主传", record: { ref: "src_002" } },
        event: { title: "瑜、普为左右督，各领万人，与备俱进，遇于赤壁，大破曹公军" },
        claims: [{
          bundle: "wuzhu",
          ref: "clm_018",
          claim: { predicate: "outcome", evidence: { text: "遇于赤壁，大破曹公军。", locator: {} } },
        }],
      },
    ],
    participants: [{
      canonical_entity_id: CAO_CAO,
      display: { name: "曹操", type: "person" },
      source_roles: [{ bundle: "wudi", event_ref: "evt_022", entity_ref: "ent_001", role: "commander" }],
    }],
    places: [{
      canonical_entity_id: RED_CLIFFS_PLACE,
      display: { name: "赤壁", type: "place" },
      source_refs: [{ bundle: "wudi", event_ref: "evt_022", entity_ref: "ent_010" }],
    }],
    related_events: [{
      type: "related_occurrence",
      event: {
        canonical_event_id: JIANGLING,
        display: { title: "曹操北还并留军守江陵、襄阳", type: "military" },
        time: { start_year: 208, end_year: 208, status: "single_year" },
      },
      provenance: [],
    }],
    resolution_links: [{
      candidate_id: "vc_001",
      decision: "same_occurrence",
      confidence: 0.98,
      rationale: "两来源描述同一赤壁交战。",
      signals: { time: "208" },
      left: { canonical_event_id: RED_CLIFFS },
      right: { canonical_event_id: RED_CLIFFS },
    }],
  });

  assert.match(html, /三国志·魏书·武帝纪/);
  assert.match(html, /三国志·吴书·吴主传/);
  assert.match(html, /公至赤壁，与备战，不利。/);
  assert.match(html, /遇于赤壁，大破曹公军。/);
  assert.match(html, new RegExp(`/entities/${CAO_CAO}`));
  assert.match(html, new RegExp(`/entities/${RED_CLIFFS_PLACE}`));
  assert.match(html, new RegExp(`/events/${JIANGLING}`));
  assert.match(html, /相关但不同事件/);
  assert.match(html, /同一事件/);
});

test("Entity Detail exposes trajectory, place involvement, and uncertain identity", () => {
  const html = renderEntity({
    schema: "chronicle.entity-detail",
    version: "0.1",
    canonical_entity_id: RED_CLIFFS_PLACE,
    display: { name: "赤壁", type: "place" },
    representation_count: 1,
    source_count: 1,
    representations: [{
      bundle: "wudi",
      ref: "ent_010",
      source: { title: "三国志·魏书·武帝纪", record: {} },
      entity: { canonical_name: "赤壁", aliases: [] },
      claims: [],
    }],
    events: [{
      canonical_event_id: RED_CLIFFS,
      display: { title: "赤壁之战", type: "battle" },
      time: { start_year: 208, end_year: 208, status: "single_year" },
      source_involvements: [{
        bundle: "wudi",
        entity_ref: "ent_010",
        event_ref: "evt_022",
        participant_roles: [],
        as_place: true,
      }],
    }],
    claims: [],
    resolution_links: [{
      candidate_id: "vc_010",
      decision: "uncertain",
      confidence: 0.55,
      rationale: "同名地点但现有来源不足以证明身份完全相同。",
      signals: { name: "赤壁" },
      left: { canonical_entity_id: RED_CLIFFS_PLACE },
      right: { canonical_entity_id: OTHER_RED_CLIFFS_PLACE },
    }],
  });

  assert.match(html, /作为地点/);
  assert.match(html, new RegExp(`/events/${RED_CLIFFS}`));
  assert.match(html, /身份不确定/);
  assert.match(html, /不足以证明身份完全相同/);
  assert.match(html, new RegExp(`/entities/${OTHER_RED_CLIFFS_PLACE}`));
  assert.doesNotMatch(html, /同一实体/);
});

test("dynamic source text is escaped rather than injected as HTML", () => {
  assert.equal(escapeHTML("<script>alert('x')</script>"), "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;");
  const html = renderTimeline({
    query: { limit: 50, offset: 0 },
    page: { total: 1, returned: 1, has_more: false },
    items: [{
      canonical_event_id: RED_CLIFFS,
      display: { title: "<img src=x onerror=alert(1)>", type: "battle" },
      time: { start_year: 208, end_year: 208 },
      source_titles: [],
    }],
  });
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

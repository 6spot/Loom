#!/usr/bin/env node
// C2-R1-T11 continuous-review smoke.
//
// Two modes:
//
//   mocked-api (default) — drives a REAL Chromium over the review queue +
//     detail pages and mocks the Studio HTTP responses, proving actual page
//     behavior (sticky bottom action bar, save-and-next advance, skip, draft
//     restore, 409 retention, entity/event isolation) without claiming a
//     real-backend chain. The full offline backend gate belongs to T18.
//
//   real-backend — no HTTP mocking: logs into a live Studio, opens a real
//     review from a prepared job/publication, selects a decision, submits and
//     asserts the server resolved it. Credentials come from the environment
//     (or flags) and are never written to the repository or logs. The caller
//     is responsible for the prepared data.
//
// Usage:
//   npm --prefix apps/chronicle/webapp run dev  # isolated Vite service first
//   node apps/chronicle/webapp/scripts/review-flow-smoke.mjs \
//     --base-url http://127.0.0.1:5173 --mode mocked-api --suite queue
//
//   CHRONICLE_SMOKE_USERNAME=... CHRONICLE_SMOKE_PASSWORD=... \
//   node apps/chronicle/webapp/scripts/review-flow-smoke.mjs \
//     --base-url http://127.0.0.1:8090 --mode real-backend \
//     --review-id <uuid> [--job-id <uuid>]
//
// Flags: --base-url <url> (required), --mode mocked-api|real-backend,
// --suite queue|all (mocked-api only, default queue),
// --review-id <uuid> / --username / --password (real-backend; username and
// password fall back to CHRONICLE_SMOKE_USERNAME / CHRONICLE_SMOKE_PASSWORD).
import { chromium } from "@playwright/test";

const args = process.argv.slice(2);
function flag(name) {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : null;
}

const BASE_URL = (flag("--base-url") || "").replace(/\/+$/, "");
const MODE = flag("--mode") || "mocked-api";
const SUITE = flag("--suite") || "queue";
const REVIEW_ID = flag("--review-id");
const JOB_ID = flag("--job-id");
const USERNAME = flag("--username") || process.env.CHRONICLE_SMOKE_USERNAME || "";
const PASSWORD = flag("--password") || process.env.CHRONICLE_SMOKE_PASSWORD || "";

if (!BASE_URL) {
  console.error("review-flow smoke: FAIL: --base-url is required (start an isolated Vite service first)");
  process.exit(1);
}
if (!["mocked-api", "real-backend"].includes(MODE)) {
  console.error(`review-flow smoke: FAIL: unsupported --mode ${MODE} (expected mocked-api|real-backend)`);
  process.exit(1);
}
if (MODE === "mocked-api" && !["queue", "all"].includes(SUITE)) {
  console.error(`review-flow smoke: FAIL: unsupported --suite ${SUITE} (expected queue|all)`);
  process.exit(1);
}
if (MODE === "real-backend" && (!USERNAME || !PASSWORD)) {
  console.error(
    "review-flow smoke: FAIL: real-backend needs credentials via --username/--password " +
      "or CHRONICLE_SMOKE_USERNAME/CHRONICLE_SMOKE_PASSWORD",
  );
  process.exit(1);
}

// ---- Mock dataset: 65 open items across 2 jobs x 2 kinds, stable order. ----
const FP = "f".repeat(64);
const OBSERVED = "2026-09-08T00:00:00+00:00";
const TOTAL = 65;
const ITEMS = [];
for (let i = 0; i < TOTAL; i += 1) {
  const kind = i % 2 === 0 ? "entity" : "event";
  const job = i % 3 === 0 ? "job-smoke-b" : "job-smoke-a";
  ITEMS.push({
    review_id: `r-smoke-${String(i).padStart(3, "0")}`,
    kind: "stage_gate",
    status: "open",
    job_id: job,
    job_status: "needs_review",
    link_kind: kind,
    created_at: `2026-09-0${1 + (i % 7)}T00:00:0${i % 10}+00:00`,
    candidate_id: `cand-${i}`,
    resolution_sha256: `reso${String(i).padStart(56, "0")}`,
    document: { title: " smoke 史料", revision_no: 1 },
    left_label: `已发布${i}`,
    right_label: `来源${i}`,
    member_count: 1,
    group_count: 1,
    suggestion: { decision: null, confidence: null, signals: [] },
    decision: null,
  });
}
// Two-item job scope used for the skip-to-end scenario.
const SMALL_JOB = "job-smoke-small";
const SMALL_IDS = ["r-small-0", "r-small-1"];
for (const id of SMALL_IDS) {
  ITEMS.push({
    review_id: id,
    kind: "stage_gate",
    status: "open",
    job_id: SMALL_JOB,
    job_status: "needs_review",
    link_kind: "entity",
    created_at: "2026-09-08T00:00:00+00:00",
    candidate_id: `cand-${id}`,
    resolution_sha256: "0".repeat(60),
    document: { title: " smoke 小作业", revision_no: 1 },
    left_label: "已发布",
    right_label: "来源",
    member_count: 1,
    group_count: 1,
    suggestion: { decision: null, confidence: null, signals: [] },
    decision: null,
  });
}
// C2-R1-T12 evidence items: long chapter, same-name groups, no-claim, failure.
const EVIDENCE_LONG_ID = "r-evidence-long";
const EVIDENCE_GROUPS_ID = "r-evidence-groups";
const EVIDENCE_NOCLAIM_ID = "r-evidence-noclaim";
const EVIDENCE_FAIL_ID = "r-evidence-fail";
const EVIDENCE_RACE_ID = "r-evidence-race";
const LONG_CHAPTER_TEXT = "列传文字。".repeat(4000);
const LONG_ANCHOR_START = 8000;
const LONG_ANCHOR_END = 8012;
const FAIL_ANCHOR = "anc-fail-1";
const failAttempts = new Map();

function evidenceDescriptor(reviewId, bundle, ref, overrides = {}) {
  return {
    context_id: `ctx-${reviewId}-${ref}`,
    bundle,
    bundle_sha256: "b".repeat(64),
    record_ref: ref,
    link_kind: "entity",
    job_id: "job-smoke-a",
    revision_id: "rev-smoke",
    chapter_id: "ch-smoke-1",
    chapter_index: 0,
    chapter_title: " smoke 章",
    artifact_sha256: "a".repeat(64),
    source_title: " smoke 文献",
    source_sha256: "s".repeat(64),
    evidence_kinds: ["direct_claim", "mention", "record_source"],
    available: true,
    unavailable_reason: null,
    anchor_count: 1,
    anchors: [{ anchor_id: `anc-${ref}`, chapter_id: "ch-smoke-1", start: 8, end: 12, quote_sha256: "q" }],
    ...overrides,
  };
}

function contextsPayload(reviewId, url) {
  const groupId = url.searchParams.get("group_id");
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || "50"), 1), 100);
  const cursor = url.searchParams.get("cursor");
  let all = [];
  if (reviewId === EVIDENCE_GROUPS_ID) {
    const groupA = [
      evidenceDescriptor(reviewId, "incoming", "g-a-1"),
      evidenceDescriptor(reviewId, "incoming", "g-a-2"),
    ];
    const groupB = [evidenceDescriptor(reviewId, "incoming", "g-b-1")];
    if (groupId === "rg-ev-a") all = groupA;
    else if (groupId === "rg-ev-b") all = groupB;
    else all = [...groupA, ...groupB];
  } else if (reviewId === EVIDENCE_LONG_ID) {
    all = [evidenceDescriptor(reviewId, "incoming", "long-1", {
      chapter_id: "ch-long", chapter_title: " smoke 长章",
      anchors: [{ anchor_id: "anc-long-1", chapter_id: "ch-long", start: LONG_ANCHOR_START, end: LONG_ANCHOR_END, quote_sha256: "q" }],
    })];
  } else if (reviewId === EVIDENCE_NOCLAIM_ID) {
    all = [evidenceDescriptor(reviewId, "incoming", "nc-1", {
      evidence_kinds: ["record_source", "mention", "translation"],
      anchors: [{ anchor_id: "anc-nc-1", chapter_id: "ch-smoke-1", start: 0, end: 4, quote_sha256: "q" }],
    })];
  } else if (reviewId === EVIDENCE_FAIL_ID) {
    all = [evidenceDescriptor(reviewId, "incoming", "fail-1", {
      anchors: [{ anchor_id: FAIL_ANCHOR, chapter_id: "ch-smoke-1", start: 0, end: 4, quote_sha256: "q" }],
    })];
  } else if (reviewId === EVIDENCE_RACE_ID) {
    all = [evidenceDescriptor(reviewId, "incoming", "race-1", {
      chapter_id: "ch-race",
      chapter_title: " smoke 竞态章",
      anchors: [
        { anchor_id: "anc-race-a", chapter_id: "ch-race", start: 0, end: 4, quote_sha256: "qa" },
        { anchor_id: "anc-race-b", chapter_id: "ch-race", start: 10, end: 14, quote_sha256: "qb" },
      ],
    })];
  } else {
    all = [evidenceDescriptor(reviewId, "incoming", `right-${reviewId}`)];
  }
  let start = 0;
  if (cursor) {
    const match = cursor.match(/^ev-(\d+)$/);
    if (!match) {
      return { status: 400, body: { schema: "chronicle.error", version: "0.1", error: { code: "bad_request", message: "invalid context cursor" } } };
    }
    start = Number(match[1]);
  }
  // Same-name batch: first page holds back one member so the UI must offer
  // an explicit expand-all instead of presenting the first page as the group.
  let end = start + limit;
  if (reviewId === EVIDENCE_GROUPS_ID && !groupId && !cursor) end = Math.min(start + 2, all.length);
  const slice = all.slice(start, end);
  const hasMore = end < all.length;
  return {
    status: 200,
    body: {
      schema: "chronicle.review-source-contexts",
      version: "0.1",
      review_id: reviewId,
      group_id: groupId,
      total: all.length,
      items: slice,
      has_more: hasMore,
      next_cursor: hasMore ? `ev-${end}` : null,
    },
  };
}

async function sourcePayload(reviewId, anchorId, url) {
  // T12 race probe: anchor A's chapter page is slow; switching to anchor B
  // must invalidate A's flight so its late text never lands under B.
  if (anchorId === "anc-race-a" || anchorId === "anc-race-b") {
    const view = url.searchParams.get("view") || "window";
    if (view === "window") {
      const text = "前后文片段。";
      return {
        status: 200,
        body: {
          schema: "chronicle.review-source", version: "0.1", review_id: reviewId, anchor_id: anchorId,
          view: "window", revision_id: "rev-smoke", source_sha256: "s".repeat(64), chapter_id: "ch-race",
          bundle: "incoming", record_ref: "race-1",
          bounds: { start: 0, end: 4, slice_start: 0, slice_end: text.length, chapter_start: 0, chapter_end: text.length, chapter_length: text.length },
          source_hash: "h", chapter_hash: "h", text,
          segments: [{ text, highlight: false }],
          has_more: false, next_cursor: null,
        },
      };
    }
    const marker = anchorId === "anc-race-a" ? "RACE-A-MARKER" : "RACE-B-MARKER";
    if (anchorId === "anc-race-a") await new Promise((done) => setTimeout(done, 2500));
    const text = `${marker}：整章分页正文。`;
    return {
      status: 200,
      body: {
        schema: "chronicle.review-source", version: "0.1", review_id: reviewId, anchor_id: anchorId,
        view: "chapter", revision_id: "rev-smoke", source_sha256: "s".repeat(64), chapter_id: "ch-race",
        bundle: "incoming", record_ref: "race-1",
        bounds: { start: 0, end: 4, slice_start: 0, slice_end: text.length, chapter_start: 0, chapter_end: text.length, chapter_length: text.length },
        source_hash: "h", chapter_hash: "h", text,
        segments: [{ text, highlight: false }],
        has_more: false, next_cursor: null,
      },
    };
  }
  if (anchorId === FAIL_ANCHOR) {
    const seen = failAttempts.get(anchorId) || 0;
    failAttempts.set(anchorId, seen + 1);
    if (seen === 0) {
      return { status: 409, body: { schema: "chronicle.error", version: "0.1", error: { code: "source_unavailable", message: "revision source is not configured" } } };
    }
  }
  const view = url.searchParams.get("view") || "window";
  const evil = '<img src=x onerror="alert(1)">军次襄阳。';
  if (anchorId === "anc-long-1" && view === "chapter") {
    const cursor = url.searchParams.get("cursor");
    const offset = cursor ? Number(cursor.split("off-")[1]) : 0;
    if (!Number.isInteger(offset) || offset < 0 || offset > LONG_CHAPTER_TEXT.length) {
      return { status: 400, body: { schema: "chronicle.error", version: "0.1", error: { code: "bad_request", message: "bad chapter cursor" } } };
    }
    const sliceEnd = Math.min(offset + 16000, LONG_CHAPTER_TEXT.length);
    const text = LONG_CHAPTER_TEXT.slice(offset, sliceEnd);
    const hasMore = sliceEnd < LONG_CHAPTER_TEXT.length;
    const lo = Math.max(offset, LONG_ANCHOR_START);
    const hi = Math.min(sliceEnd, LONG_ANCHOR_END);
    const segments = [];
    if (lo > offset) segments.push({ text: LONG_CHAPTER_TEXT.slice(offset, lo).slice(-200), highlight: false });
    segments.push({ text: LONG_CHAPTER_TEXT.slice(lo, hi), highlight: true });
    if (hi < sliceEnd) segments.push({ text: LONG_CHAPTER_TEXT.slice(hi, sliceEnd).slice(0, 200), highlight: false });
    return {
      status: 200,
      body: {
        schema: "chronicle.review-source", version: "0.1", review_id: reviewId, anchor_id: anchorId,
        view: "chapter", revision_id: "rev-smoke", source_sha256: "s".repeat(64), chapter_id: "ch-long",
        bundle: "incoming", record_ref: "long-1",
        bounds: { start: LONG_ANCHOR_START, end: LONG_ANCHOR_END, slice_start: offset, slice_end: sliceEnd, chapter_start: 0, chapter_end: LONG_CHAPTER_TEXT.length, chapter_length: LONG_CHAPTER_TEXT.length },
        source_hash: "h", chapter_hash: "h", text,
        segments, has_more: hasMore, next_cursor: hasMore ? `off-${sliceEnd}` : null,
      },
    };
  }
  const windowText = anchorId === "anc-nc-1" ? "先主姓刘，讳备。" : `${evil}前后文四百字。`;
  return {
    status: 200,
    body: {
      schema: "chronicle.review-source", version: "0.1", review_id: reviewId, anchor_id: anchorId,
      view: "window", revision_id: "rev-smoke", source_sha256: "s".repeat(64), chapter_id: "ch-smoke-1",
      bundle: "incoming", record_ref: "nc",
      bounds: { start: 0, end: 4, slice_start: 0, slice_end: windowText.length, chapter_start: 0, chapter_end: 800, chapter_length: 800 },
      source_hash: "h", chapter_hash: "h", text: windowText,
      segments: [
        { text: windowText.slice(0, 8), highlight: false },
        { text: windowText.slice(8, 12), highlight: true },
        { text: windowText.slice(12), highlight: false },
      ],
      has_more: false, next_cursor: null,
    },
  };
}

// Conflict item: batch default same_entity collides with two canonicals.
const CONFLICT_ID = "r-conflict";
ITEMS.push({
  review_id: CONFLICT_ID,
  kind: "stage_gate",
  status: "open",
  job_id: "job-smoke-a",
  job_status: "needs_review",
  link_kind: "entity",
  created_at: "2026-09-09T00:00:00+00:00",
  candidate_id: "cand-conflict",
  resolution_sha256: "1".repeat(60),
  document: { title: " smoke 冲突", revision_no: 1 },
  left_label: "已发布襄阳",
  right_label: "来源襄阳",
  member_count: 2,
  group_count: 2,
  suggestion: { decision: "same_entity", confidence: 0.6, signals: ["exact_name"] },
  decision: null,
});

for (const [id, title] of [
  [EVIDENCE_LONG_ID, " smoke 长章证据"],
  [EVIDENCE_GROUPS_ID, " smoke 同名多组"],
  [EVIDENCE_NOCLAIM_ID, " smoke 无Claim"],
  [EVIDENCE_FAIL_ID, " smoke 失败重试"],
  [EVIDENCE_RACE_ID, " smoke 锚点竞态"],
]) {
  ITEMS.push({
    review_id: id,
    kind: "stage_gate",
    status: "open",
    job_id: "job-smoke-a",
    job_status: "needs_review",
    link_kind: "entity",
    created_at: "2026-09-09T00:00:00+00:00",
    candidate_id: `cand-${id}`,
    resolution_sha256: "2".repeat(60),
    document: { title, revision_no: 1 },
    left_label: "已发布",
    right_label: "来源",
    member_count: id === EVIDENCE_GROUPS_ID ? 3 : 1,
    group_count: id === EVIDENCE_GROUPS_ID ? 2 : 1,
    suggestion: { decision: null, confidence: null, signals: [] },
    decision: null,
  });
}

const resolved = new Map();
const decisionPosts = [];

function filteredItems(url) {
  const job = url.searchParams.get("job_id");
  const kind = url.searchParams.get("link_kind");
  // Mirror the server keyset: ORDER BY (created_at, review_id).
  return ITEMS.filter((item) => {
    if (resolved.has(item.review_id)) return false;
    if (job && item.job_id !== job) return false;
    if (kind && item.link_kind !== kind) return false;
    return true;
  }).sort((a, b) => {
    if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1;
    return a.review_id < b.review_id ? -1 : a.review_id > b.review_id ? 1 : 0;
  });
}

function reviewPagePayload(url) {
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || "50"), 1), 100);
  const cursor = url.searchParams.get("cursor");
  const list = filteredItems(url);
  let start = 0;
  if (cursor) {
    const match = cursor.match(/^smoke-(\d+)$/);
    if (!match) {
      return { status: 400, body: { schema: "chronicle.error", version: "0.1", error: { code: "bad_cursor", message: "invalid cursor" } } };
    }
    start = Number(match[1]);
  }
  const slice = list.slice(start, start + limit);
  const next = start + limit < list.length ? `smoke-${start + limit}` : null;
  return {
    status: 200,
    body: {
      schema: "chronicle.studio-review-page",
      version: "0.2",
      query: {
        status: url.searchParams.get("status") || "open",
        job_id: url.searchParams.get("job_id"),
        link_kind: url.searchParams.get("link_kind"),
        limit,
      },
      items: slice,
      next_cursor: next,
      open_count: list.length,
      observed_at: OBSERVED,
      plan_fingerprint: FP,
    },
  };
}

function contextFor(bundle, ref, name) {
  return {
    bundle,
    ref,
    source_title: " smoke 文献",
    record: { kind: "entity", name },
    display: {
      kind: "entity",
      name,
      evidence: [{ claim_ref: `clm-${ref}`, text: `軍次${name}。`, locator: { work: " smoke 文献", chapter: " smoke 章" } }],
    },
  };
}

function detailFor(id) {
  const item = ITEMS.find((entry) => entry.review_id === id);
  if (!item || resolved.has(id)) {
    const decided = resolved.get(id);
    if (!item) return null;
    return { ...detailBody(item), status: "resolved", decision: decided, resolved_at: OBSERVED };
  }
  return detailBody(item);
}

function detailBody(item) {
  const kind = item.link_kind;
  const left = contextFor("published", `left-${item.review_id}`, `已发布${item.review_id}`);
  let right = contextFor("incoming", `right-${item.review_id}`, `来源${item.review_id}`);
  if (item.review_id === EVIDENCE_NOCLAIM_ID) {
    right = {
      bundle: "incoming",
      ref: "nc-1",
      source_title: " smoke 文献",
      record: { kind: "entity", name: "无名氏" },
      display: { kind: "entity", name: "无名氏", evidence: [] },
    };
  }
  const groups =
    item.review_id === CONFLICT_ID
      ? [
        { review_group_id: "rg-a", member_count: 1, signals: [], right_contexts: [right] },
        { review_group_id: "rg-b", member_count: 1, signals: [], right_contexts: [right] },
      ]
      : item.review_id === EVIDENCE_GROUPS_ID
        ? [
          {
            review_group_id: "rg-ev-a",
            member_count: 2,
            signals: [],
            right_contexts: [
              contextFor("incoming", "g-a-1", "襄阳"),
              contextFor("incoming", "g-a-2", "襄阳"),
            ],
          },
          {
            review_group_id: "rg-ev-b",
            member_count: 1,
            signals: [],
            right_contexts: [contextFor("incoming", "g-b-1", "襄阳")],
          },
        ]
        : [];
  return {
    ...item,
    scope: "resolution",
    revision_id: "rev-smoke",
    chunk_id: null,
    resolved_at: null,
    blocking: true,
    allowed_decisions:
      kind === "entity"
        ? ["same_entity", "not_same", "uncertain"]
        : ["same_occurrence", "related_occurrence", "not_same", "uncertain"],
    left,
    right,
    left_context: left,
    right_context: right,
    review_groups: groups,
    group_count: groups.length || 1,
    job_open_resolution_reviews: 1,
    plan_fingerprint: FP,
  };
}

function conflictBody() {
  const incoming = contextFor("incoming", "right-r-conflict", "来源襄阳");
  return {
    schema: "chronicle.error",
    version: "0.1",
    error: {
      code: "canonical_identity_conflict",
      message: "该判断无法提交",
      details: {
        review_id: CONFLICT_ID,
        canonical_ids: ["canonical-a", "canonical-b"],
        canonical_entities: [
          { canonical_id: "canonical-a", names: ["襄阳"], contexts: [contextFor("wudi", "ent_013", "襄阳")] },
          { canonical_id: "canonical-b", names: ["襄阳"], contexts: [contextFor("wuzhu", "ent_030", "襄阳")] },
        ],
        review_group_ids: ["rg-a"],
        candidate_keys: ["artifact-a:candidate-a"],
        proposed_candidate_keys: ["artifact-a:candidate-a"],
        incoming_refs: [{ bundle: "incoming", ref: "right-r-conflict" }],
        incoming_contexts: [incoming],
        published_refs: [
          { bundle: "wudi", ref: "ent_013", canonical_id: "canonical-a" },
          { bundle: "wuzhu", ref: "ent_030", canonical_id: "canonical-b" },
        ],
        review_groups: [
          {
            review_group_id: "rg-a",
            candidate_keys: ["artifact-a:candidate-a"],
            incoming_refs: [{ bundle: "incoming", ref: "right-r-conflict" }],
            right_contexts: [incoming],
          },
        ],
      },
    },
  };
}

function check(name, cond) {
  if (!cond) throw new Error(`missing ${name}`);
  console.log(`  ok: ${name}`);
}

async function login(page) {
  await page.getByLabel("用户名").fill(USERNAME);
  await page.getByLabel("密码").fill(PASSWORD);
  await page.getByRole("button", { name: "登录管理工作台" }).click();
  await page.getByText("Studio 总览").first().waitFor({ timeout: 15000 });
}

async function queueUrl() {
  const scope = new URLSearchParams({ status: "open" });
  if (JOB_ID) scope.set("job_id", JOB_ID);
  return `${BASE_URL}/studio/review?${scope.toString()}`;
}

async function reviewCount(page) {
  const html = await page.content();
  const match = html.match(/待处理\s*(\d+)\s*项/);
  return match ? Number(match[1]) : null;
}

// Real-backend mode: no HTTP mocking. Logs into a live Studio, opens a real
// review from prepared data, submits a decision and asserts the server
// resolved it. Mutates real review state, so it is run against the disposable
// test deployment with its own prepared job/review, never production data.
async function runRealBackend(page) {
  await page.goto(await queueUrl(), { waitUntil: "networkidle" });
  await login(page);
  check("studio login (real)", true);

  await page.goto(await queueUrl(), { waitUntil: "networkidle" });
  await page.getByText("人工审核队列").first().waitFor({ timeout: 15000 });
  check("queue renders (real)", true);
  const openBefore = await reviewCount(page);
  check("server open_count shown (real)", openBefore !== null);

  let reviewId = REVIEW_ID;
  if (reviewId) {
    await page.goto(`${BASE_URL}/studio/review/${encodeURIComponent(reviewId)}?status=open`, {
      waitUntil: "networkidle",
    });
  } else {
    const link = page.locator('a:has-text("查看并判断")').first();
    await link.waitFor({ timeout: 15000 });
    const href = await link.getAttribute("href");
    reviewId = decodeURIComponent(href.split("/studio/review/")[1].split("?")[0]);
    await link.click();
  }
  await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
  check("review detail opened (real)", true);

  const decisionSelect = page.getByLabel("你的判断");
  const decision = await decisionSelect.inputValue();
  check("allowed decision preselected (real)", typeof decision === "string" && decision.length > 0);

  const rationaleId = `smoke-real-${Date.now()}`;
  await page.getByLabel("判断依据").fill(rationaleId);
  await page.waitForTimeout(300);
  const beforeUrl = page.url();
  const submittedPath = new URL(beforeUrl).pathname;
  await page.getByRole("button", { name: "保存并下一项" }).click();
  // The action bar advances to the next open review, but the submitted review
  // may be the last open item in scope, in which case the page stays put. The
  // authoritative check is the server readback below, so tolerate the terminal
  // (no-next-item) case instead of failing on a navigation timeout; still
  // surface a real error alert if the submit was rejected.
  await Promise.race([
    page.waitForURL((url) => url.pathname !== submittedPath, { timeout: 10000 }).catch(() => {}),
    page.waitForTimeout(10000),
  ]);
  const submitAlerts = await page.getByRole("alert").allInnerTexts().catch(() => []);
  const submitError = submitAlerts.map((text) => (text || "").trim()).filter(Boolean).join(" | ");
  if (submitError) {
    throw new Error(`real-backend submit surfaced an error: ${submitError.slice(0, 200)}`);
  }
  check("submit accepted (real)", true);

  // The Studio UI authenticates its own XHR with Basic credentials held in the
  // page session, not a cookie, so an out-of-band request must supply them.
  const authHeader = `Basic ${Buffer.from(`${USERNAME}:${PASSWORD}`).toString("base64")}`;
  const response = await page.request.get(
    `${BASE_URL}/api/v1/studio/jobs/reviews/${encodeURIComponent(reviewId)}`,
    { headers: { Authorization: authHeader } },
  );
  if (response.status() !== 200) {
    throw new Error(`real-backend review readback failed: HTTP ${response.status()}`);
  }
  const readback = await response.json();
  const review = readback.review || readback;
  check("server reports resolved (real)", review.status === "resolved");
  check(
    "server echoes the submitted decision (real)",
    review.decision && review.decision.decision === decision,
  );

  const afterOpen = JOB_ID ? null : await reviewCount(page).catch(() => null);
  if (afterOpen !== null && openBefore !== null) {
    check("open_count does not increase (real)", afterOpen <= openBefore);
  }
  console.log("review-flow smoke (real-backend): PASS");
}

async function runMocked(page) {
    await page.route("**/api/v1/studio/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const path = url.pathname;
      if (path === "/api/v1/studio/status") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            schema: "chronicle.status",
            version: "0.1",
            admin_user: "smoke-admin",
            upstream: { reachable: true },
          }),
        });
      }
      if (path === "/api/v1/studio/jobs/reviews" && req.method() === "GET") {
        const payload = reviewPagePayload(url);
        return route.fulfill({ status: payload.status, contentType: "application/json", body: JSON.stringify(payload.body) });
      }
      const decision = path.match(/^\/api\/v1\/studio\/jobs\/reviews\/([^/]+)\/decision$/);
      if (decision && req.method() === "POST") {
        const id = decodeURIComponent(decision[1]);
        const body = JSON.parse(req.postData() || "{}");
        decisionPosts.push({ id, body });
        if (id === CONFLICT_ID && body.decision === "same_entity" && !body.group_decisions) {
          return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify(conflictBody()) });
        }
        const decided = { decision: body.decision, confidence: body.confidence, rationale: body.rationale };
        resolved.set(id, decided);
        const item = ITEMS.find((entry) => entry.review_id === id);
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ schema: "chronicle.review", version: "0.1", review: { ...detailBody(item), status: "resolved", decision: decided, resolved_at: OBSERVED } }),
        });
      }
      const contexts = path.match(/^\/api\/v1\/studio\/jobs\/reviews\/([^/]+)\/contexts$/);
      if (contexts && req.method() === "GET") {
        const payload = contextsPayload(decodeURIComponent(contexts[1]), url);
        return route.fulfill({ status: payload.status, contentType: "application/json", body: JSON.stringify(payload.body) });
      }
      const source = path.match(/^\/api\/v1\/studio\/jobs\/reviews\/([^/]+)\/sources\/([^/]+)$/);
      if (source && req.method() === "GET") {
        const payload = await sourcePayload(decodeURIComponent(source[1]), decodeURIComponent(source[2]), url);
        return route.fulfill({ status: payload.status, contentType: "application/json", body: JSON.stringify(payload.body) });
      }
      const detail = path.match(/^\/api\/v1\/studio\/jobs\/reviews\/([^/]+)$/);
      if (detail && req.method() === "GET") {
        const body = detailFor(decodeURIComponent(detail[1]));
        if (!body) return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ schema: "chronicle.error", version: "0.1", error: { code: "not_found", message: "no such review" } }) });
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schema: "chronicle.review", version: "0.1", review: body }) });
      }
      const job = path.match(/^\/api\/v1\/studio\/jobs\/([^/]+)$/);
      if (job && req.method() === "GET") {
        const jobId = decodeURIComponent(job[1]);
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            schema: "chronicle.job",
            version: "0.1",
            job: {
              job_id: jobId,
              revision_id: "rev-smoke",
              status: "needs_review",
              attempt: 1,
              max_attempts: 3,
              lease_owner: null,
              lease_expires_at: null,
              error: null,
              created_at: OBSERVED,
              updated_at: OBSERVED,
              open_reviews: 2,
              stages: [],
              chunks: [],
              reviews: [],
              outputs: [],
            },
          }),
        });
      }
      return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ schema: "chronicle.error", version: "0.1", error: { code: "not_found", message: "smoke mock has no such route" } }) });
    });

    // Login through the real form (mocked status endpoint).
    await page.goto(`${BASE_URL}/studio/review?status=open`, { waitUntil: "networkidle" });
    await page.getByLabel("用户名").fill("smoke-admin");
    await page.getByLabel("密码").fill("smoke-pass");
    await page.getByRole("button", { name: "登录管理工作台" }).click();
    await page.getByText("Studio 总览").first().waitFor({ timeout: 15000 });
    check("studio login", true);

    await page.goto(`${BASE_URL}/studio/review?status=open`, { waitUntil: "networkidle" });
    await page.getByText("人工审核队列").first().waitFor({ timeout: 15000 });

    // 1. Queue renders the server page with open_count.
    const queueHTML = await page.content();
    check("queue renders", queueHTML.includes("人工审核队列"));
    check("server open_count shown", /待处理 \d+ 项/.test(queueHTML));
    const queueUrl = new URL(page.url());
    check("scope in URL", queueUrl.searchParams.get("status") === "open");

    // 2. Kind filter rewrites the URL scope and the list.
    await page.getByRole("button", { name: "事件发生", exact: true }).click();
    await page.waitForURL(/link_kind=event/, { timeout: 10000 });
    const eventUrl = new URL(page.url());
    check("kind scope in URL", eventUrl.searchParams.get("link_kind") === "event");
    await page.getByRole("button", { name: "全部种类" }).click();
    await page.waitForURL((url) => !url.searchParams.has("link_kind"), { timeout: 10000 });

    // 3. Keyset pagination across a 65-item mocked queue.
    const nextButton = page.getByRole("button", { name: "下一页" });
    await nextButton.scrollIntoViewIfNeeded();
    check("next page enabled on page one", await nextButton.isEnabled());
    await nextButton.click();
    await page.getByText("上次位置").first().waitFor({ timeout: 10000 }).catch(() => {});
    const prevButton = page.getByRole("button", { name: "上一页" });
    check("previous page enabled on page two", await prevButton.isEnabled());
    await prevButton.click();
    await page.waitForTimeout(800);

    // 4. Detail bottom action bar is reachable without scrolling to top.
    const firstDetail = page.locator('a:has-text("查看并判断")').first();
    const firstHref = await firstDetail.getAttribute("href");
    const firstId = decodeURIComponent(firstHref.split("/studio/review/")[1].split("?")[0]);
    await firstDetail.click();
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    const bar = page.getByRole("toolbar", { name: "连续审核操作" });
    const box = await bar.boundingBox();
    check("bottom action bar visible without scrolling back", box !== null && box.y + box.height <= 900 + 400);
    check("save-and-next present", (await bar.getByRole("button", { name: "保存并下一项" }).count()) === 1);
    check("skip present", (await bar.getByRole("button", { name: "暂时跳过" }).count()) === 1);
    check("back present", (await bar.getByRole("button", { name: "返回队列" }).count()) === 1);

    // 5. Draft survives reload; save-and-next advances and clears it.
    await page.getByLabel("判断依据").fill("smoke草稿-证据充分");
    await page.waitForTimeout(500);
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    check("draft retained after reload", (await page.getByLabel("判断依据").inputValue()) === "smoke草稿-证据充分");
    await bar.getByRole("button", { name: "保存并下一项" }).click();
    await page.waitForURL((url) => url.pathname !== `/studio/review/${firstId}`, { timeout: 15000 });
    const nextId = page.url().split("/studio/review/")[1].split("?")[0];
    check("save-and-next advances", decodeURIComponent(nextId) !== firstId);
    check("decision posted once", decisionPosts.filter((post) => post.id === firstId).length === 1);

    // 6. Skip navigates without posting a decision.
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    const skipId = decodeURIComponent(page.url().split("/studio/review/")[1].split("?")[0]);
    await page.getByRole("button", { name: "暂时跳过" }).click();
    await page.waitForURL((url) => !url.pathname.endsWith(skipId), { timeout: 15000 });
    check("skip posts no decision", !decisionPosts.some((post) => post.id === skipId));

    // 7. Back to queue keeps the scope in the URL.
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    await page.getByRole("button", { name: "返回队列" }).click();
    await page.getByText("人工审核队列").first().waitFor({ timeout: 15000 });
    check("back keeps scope", new URL(page.url()).pathname === "/studio/review");

    // 7b. Deep-page regression: saving an item past page one must continue
    // after its (created_at, review_id) anchor, not restart at the head.
    const sortedOpen = [...ITEMS]
      .filter((item) => !resolved.has(item.review_id))
      .sort((a, b) => {
        if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1;
        return a.review_id < b.review_id ? -1 : a.review_id > b.review_id ? 1 : 0;
      });
    const deepItem = sortedOpen.find((item) => {
      const index = sortedOpen.indexOf(item);
      return index >= 50 && item.status === "open" && !decisionPosts.some((post) => post.id === item.review_id);
    });
    const deepIndex = sortedOpen.indexOf(deepItem);
    const deepExpected = sortedOpen.slice(deepIndex + 1).find(
      (item) => item.review_id !== skipId && !decisionPosts.some((post) => post.id === item.review_id),
    );
    await page.goto(`${BASE_URL}/studio/review/${deepItem.review_id}?status=open`, { waitUntil: "networkidle" });
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    await page.getByLabel("判断依据").fill("smoke深页草稿");
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: "保存并下一项" }).click();
    await page.waitForURL((url) => url.pathname !== `/studio/review/${deepItem.review_id}`, { timeout: 15000 });
    const deepNext = decodeURIComponent(page.url().split("/studio/review/")[1].split("?")[0]);
    check("deep-page save continues after the anchor", deepNext === deepExpected.review_id);

    // 8. 409 conflict keeps the draft and the per-group work.
    await page.goto(`${BASE_URL}/studio/review/${CONFLICT_ID}?status=open`, { waitUntil: "networkidle" });
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    await page.getByLabel("判断依据").fill("smoke冲突草稿");
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: "保存并下一项" }).click();
    await page.getByRole("alert").waitFor({ timeout: 15000 });
    check("conflict notice shown", (await page.content()).includes("该判断无法提交"));
    check("conflict retains draft", (await page.getByLabel("判断依据").inputValue()) === "smoke冲突草稿");
    await page.reload({ waitUntil: "networkidle" });
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    check("conflict draft survives reload", (await page.getByLabel("判断依据").inputValue()) === "smoke冲突草稿");

    // 9. Entity→Event never carries an illegal decision (untouched ids).
    const entityId = "r-smoke-004";
    const eventId = "r-smoke-005";
    await page.goto(`${BASE_URL}/studio/review/${entityId}?status=open`, { waitUntil: "networkidle" });
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    check("entity vocabulary", (await page.getByLabel("你的判断").inputValue()) === "same_entity");
    await page.goto(`${BASE_URL}/studio/review/${eventId}?status=open`, { waitUntil: "networkidle" });
    await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
    check("event vocabulary isolated", (await page.getByLabel("你的判断").inputValue()) === "same_occurrence");

    // 10. Skipping the only items in a scope reports the still-open count.
    await page.goto(`${BASE_URL}/studio/review?status=open&job_id=${SMALL_JOB}`, { waitUntil: "networkidle" });
    await page.getByText("人工审核队列").first().waitFor({ timeout: 15000 });
    for (const id of SMALL_IDS) {
      await page.goto(`${BASE_URL}/studio/review/${id}?status=open&job_id=${SMALL_JOB}`, { waitUntil: "networkidle" });
      await page.getByRole("toolbar", { name: "连续审核操作" }).waitFor({ timeout: 15000 });
      await page.getByRole("button", { name: "暂时跳过" }).click();
      await page.waitForTimeout(1500);
    }
    await page.getByText(/本轮已查看，仍有 2 项暂时跳过/).waitFor({ timeout: 15000 });
    check("only-skipped end state counts still-open skips", true);

    if (SUITE === "all") {
      // 11. Job-scoped entry from the import detail page.
      await page.goto(`${BASE_URL}/studio/imports/${SMALL_JOB}`, { waitUntil: "networkidle" });
      await page.getByRole("link", { name: "进入该作业的审核队列" }).click();
      await page.getByText("人工审核队列").first().waitFor({ timeout: 15000 });
      const jobUrl = new URL(page.url());
      check("job scope entry", jobUrl.searchParams.get("job_id") === SMALL_JOB);

      // 12. Evidence section: window snippet expands inline, HTML is inert.
      await page.goto(`${BASE_URL}/studio/review/${EVIDENCE_LONG_ID}?status=open`, { waitUntil: "networkidle" });
      await page.getByText("审核证据与来源").first().waitFor({ timeout: 15000 });
      check("evidence section present", true);
      await page.getByRole("button", { name: "展开原文" }).first().click();
      await page.locator(".evidence-text").first().waitFor({ timeout: 15000 });
      check("window snippet shown", (await page.locator(".evidence-text").first().textContent()).includes("前后文"));
      check("malicious html not executed", (await page.locator(".evidence-text img").count()) === 0);
      check("server highlight rendered", (await page.locator(".evidence-text mark").count()) >= 1);

      // 13. Long chapter: explicit unfinished state plus continued paging.
      // "整章阅读" loads the first page by itself; only "分页续读" advances.
      await page.getByRole("button", { name: "整章阅读" }).first().click();
      await page.getByText("本章还有未完分页").first().waitFor({ timeout: 15000 });
      check("chapter unfinished state explicit", true);
      await page.getByRole("button", { name: /分页续读/ }).first().click();
      await page.getByText("已读完本章全部内容").first().waitFor({ timeout: 15000 });
      check("chapter continued to the end", true);

      // 14. Same-name groups: first page is not the whole group; per-group
      // evidence is checkable inside the exception cards.
      await page.goto(`${BASE_URL}/studio/review/${EVIDENCE_GROUPS_ID}?status=open`, { waitUntil: "networkidle" });
      await page.getByText("审核证据与来源").first().waitFor({ timeout: 15000 });
      await page.getByText(/已加载 2 \/ 共 3 个候选来源/).first().waitFor({ timeout: 15000 });
      check("group members not reduced to first page", true);
      await page.getByRole("button", { name: /展开全部成员/ }).first().click();
      await page.getByText(/已加载 3 \/ 共 3 个候选来源/).first().waitFor({ timeout: 15000 });
      check("expand-all loads every member", true);
      await page.getByRole("button", { name: "存在例外，展开逐组判断" }).click();
      await page.getByText("候选组 1 的逐组来源").waitFor({ timeout: 15000 });
      check("per-group evidence checkable", (await page.getByText("候选组 2 的逐组来源").count()) === 1);

      // 15. No-claim record falls back to record_source/mention material.
      await page.goto(`${BASE_URL}/studio/review/${EVIDENCE_NOCLAIM_ID}?status=open`, { waitUntil: "networkidle" });
      await page.getByText("审核证据与来源").first().waitFor({ timeout: 15000 });
      await page.getByRole("button", { name: "展开原文" }).first().click();
      await page.getByText(/没有直接关联的事实声明/).first().waitFor({ timeout: 15000 });
      check("no-claim fallback shown", true);
      check("translation marked auxiliary", (await page.getByText(/白话译文仅供辅助参考/).count()) >= 1);

      // 16. Source failure keeps the form and the draft, then retries.
      await page.goto(`${BASE_URL}/studio/review/${EVIDENCE_FAIL_ID}?status=open`, { waitUntil: "networkidle" });
      await page.getByText("审核证据与来源").first().waitFor({ timeout: 15000 });
      await page.getByLabel("判断依据").fill("smoke证据失败草稿");
      await page.waitForTimeout(500);
      await page.getByRole("button", { name: "展开原文" }).first().click();
      await page.getByRole("button", { name: "重试加载原文" }).first().waitFor({ timeout: 15000 });
      check("failure keeps form with retry", true);
      check("draft retained across failure", (await page.getByLabel("判断依据").inputValue()) === "smoke证据失败草稿");
      await page.getByRole("button", { name: "重试加载原文" }).first().click();
      await page.locator(".evidence-text").first().waitFor({ timeout: 15000 });
      check("retry recovers the source", true);

      // 17. Anchor race: a slow chapter page for anchor A must not land
      // under anchor B after the reviewer switches anchors mid-flight.
      await page.goto(`${BASE_URL}/studio/review/${EVIDENCE_RACE_ID}?status=open`, { waitUntil: "networkidle" });
      await page.getByText("审核证据与来源").first().waitFor({ timeout: 15000 });
      await page.getByRole("button", { name: "展开原文" }).first().click();
      await page.getByRole("button", { name: "整章阅读" }).first().click();
      await page.getByLabel("定位锚点（同组多个出现位置分别可查）").selectOption("anc-race-b");
      await page.getByRole("button", { name: "整章阅读" }).first().click();
      await page.getByText("RACE-B-MARKER").first().waitFor({ timeout: 15000 });
      check("new anchor chapter loads", true);
      await page.waitForTimeout(3500);
      check("stale anchor response dropped", (await page.getByText("RACE-A-MARKER").count()) === 0);
      check("decision draft untouched by the race", (await page.getByLabel("判断依据").inputValue()) === "");
    }

    console.log(`review-flow smoke (${SUITE}, mocked-api): PASS`);
}

async function main() {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on("dialog", (dialog) => void dialog.accept());
    if (MODE === "real-backend") {
      await runRealBackend(page);
    } else {
      await runMocked(page);
    }
  } finally {
    await browser.close();
  }
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error(`review-flow smoke: FAIL: ${err.message}`);
    process.exit(1);
  },
);

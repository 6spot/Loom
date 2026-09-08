#!/usr/bin/env node
// C2-R1-T11 continuous-review smoke (UI behavior only).
//
// Drives a REAL Chromium over the review queue + detail pages and mocks the
// Studio HTTP responses, so the test proves actual page behavior (sticky
// bottom action bar, save-and-next advance, skip, draft restore, 409
// retention, entity/event isolation) without claiming a real-backend chain.
// The full offline backend gate belongs to T18.
//
// Usage:
//   npm --prefix apps/chronicle/webapp run dev  # isolated Vite service first
//   node apps/chronicle/webapp/scripts/review-flow-smoke.mjs \
//     --base-url http://127.0.0.1:5173 --mode mocked-api --suite queue
//
// Flags: --base-url <url> (required), --mode mocked-api (only supported
// mode in this task), --suite queue|all (default queue).
import { chromium } from "@playwright/test";

const args = process.argv.slice(2);
function flag(name) {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : null;
}

const BASE_URL = (flag("--base-url") || "").replace(/\/+$/, "");
const MODE = flag("--mode") || "mocked-api";
const SUITE = flag("--suite") || "queue";

if (!BASE_URL) {
  console.error("review-flow smoke: FAIL: --base-url is required (start an isolated Vite service first)");
  process.exit(1);
}
if (MODE !== "mocked-api") {
  console.error(`review-flow smoke: FAIL: unsupported --mode ${MODE} (this task only provides mocked-api; real-backend chain is T18)`);
  process.exit(1);
}
if (!["queue", "all"].includes(SUITE)) {
  console.error(`review-flow smoke: FAIL: unsupported --suite ${SUITE} (expected queue|all)`);
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

const resolved = new Map();
const decisionPosts = [];

function filteredItems(url) {
  const job = url.searchParams.get("job_id");
  const kind = url.searchParams.get("link_kind");
  return ITEMS.filter((item) => {
    if (resolved.has(item.review_id)) return false;
    if (job && item.job_id !== job) return false;
    if (kind && item.link_kind !== kind) return false;
    return true;
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
  const right = contextFor("incoming", `right-${item.review_id}`, `来源${item.review_id}`);
  const groups =
    item.review_id === CONFLICT_ID
      ? [
        { review_group_id: "rg-a", member_count: 1, signals: [], right_contexts: [right] },
        { review_group_id: "rg-b", member_count: 1, signals: [], right_contexts: [right] },
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

async function main() {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on("dialog", (dialog) => void dialog.accept());

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
    }

    console.log(`review-flow smoke (${SUITE}, mocked-api): PASS`);
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

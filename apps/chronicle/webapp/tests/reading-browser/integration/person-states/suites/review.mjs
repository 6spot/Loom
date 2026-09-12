// C2-R3-T14 integrated mixed-review suite.
//
// Operates the real Studio review queue against the running stack. The gate
// parks one genuine source job on its `chapter_state_evidence` packages and
// one genuine synthesis job on its facts review, so this suite proves the real
// queue exposes both the person-state and the narrative form and that opening
// each renders the reviewed package. Full paging/save-next/409/draft coverage
// lives in the registered component suite `person-state-review` (run by
// `r3-all`), which this suite complements with the real-backend proof.

import { reviewUrl } from "../manifest.mjs";

export const TASK = "C2-R3-T14";

const USERNAME = process.env.CHRONICLE_SMOKE_USERNAME || "";
const PASSWORD = process.env.CHRONICLE_SMOKE_PASSWORD || "";

async function studioLogin(page, baseUrl) {
  await page.goto(new URL("/studio/login", baseUrl).toString(), {
    waitUntil: "domcontentloaded",
  });
  await page.fill("#studio-username", USERNAME);
  await page.fill("#studio-password", PASSWORD);
  await page.getByRole("button", { name: "登录管理工作台" }).click();
  await page.waitForURL(/\/studio(?!\/login)/, { timeout: 30000 });
}

async function openScopePanel(page, runner, baseUrl, jobId, badgeText, panelTestId) {
  await page.goto(reviewUrl(baseUrl, { review_scope: "all" }, jobId), {
    waitUntil: "domcontentloaded",
  });
  const row = page.locator(".studio-table-row", { hasText: badgeText }).first();
  await row.waitFor({ timeout: 30000 });
  runner.check(`queue_exposes_${panelTestId}`, true);
  await row.getByRole("link", { name: "查看并判断" }).click();
  await page.waitForURL(/\/studio\/review\//, { timeout: 30000 });
  await page.locator(`[data-test="${panelTestId}"]`).waitFor({ timeout: 30000 });
  runner.check(`detail_renders_${panelTestId}`, true);
}

export async function run(ctx) {
  const { baseUrl, manifest, runner } = ctx;
  if (!USERNAME || !PASSWORD) {
    throw new Error("person-state review suite requires CHRONICLE_SMOKE_USERNAME/PASSWORD");
  }
  const page = await runner.newPage({ viewport: { width: 1440, height: 900 } });
  await studioLogin(page, baseUrl);

  // Person-state chapter-basis form.
  await openScopePanel(
    page,
    runner,
    baseUrl,
    manifest.review.person_state_job_id,
    "阶段依据",
    "person-state-review-panel",
  );
  const candidates = page.locator('[data-test="psr-candidate"]');
  runner.check("person_state_candidates_present", (await candidates.count()) >= 1, "no candidate rows");
  const rationale = page.locator('[data-test="psr-rationale"]');
  runner.check("person_state_rationale_editable", (await rationale.count()) >= 1, "no rationale field");
  await rationale.first().fill("浏览器验收：逐项核对原文后记录草稿。");
  runner.check("person_state_draft_typed", (await rationale.first().inputValue()).length > 0);
  const firstAssessment = page.locator('[data-test="psr-assessment"]').first();
  if ((await firstAssessment.count()) >= 1) {
    await firstAssessment.focus();
    runner.check("person_state_assessment_focusable", await firstAssessment.evaluate((el) => el === document.activeElement));
  }
  await runner.screenshot(page, "review-person-state");

  // Narrative facts/prose forms are exercised by the registered component
  // suites (narrative-review-component-smoke.mjs and person-state-review);
  // when the gate also parks a narrative review, open it here too.
  if (manifest.review.narrative_job_id) {
    await openScopePanel(
      page,
      runner,
      baseUrl,
      manifest.review.narrative_job_id,
      "事实核对",
      "narrative-review-actions",
    );
    runner.check("narrative_form_rendered", true);
    await runner.screenshot(page, "review-narrative");
  }
}

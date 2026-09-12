// C2-R3-T14 integrated person-state reading suite.
//
// Operates the real published HistoryPage and the independent person page of
// the running Rust/Python/PG stack. It pins the exact `{version, paragraph_id,
// phase_id}` the gate published, proves the reviewed two-tier state reaches
// the composite body and the person page, and proves the in-place return.
// Viewport/keyboard/touch/zoom breadth is covered by the registered component
// suites (`r3-all`); this suite carries the real-backend terminal proof.

import { historyUrl } from "../manifest.mjs";

export const TASK = "C2-R3-T14";

async function waitPhaseReady(page, phaseId) {
  await page.waitForFunction(
    (wanted) => {
      const node = document.querySelector('[data-test="history-phase-status"]');
      return Boolean(node) && node.getAttribute("data-status") === "ready" && node.getAttribute("data-phase-id") === wanted;
    },
    phaseId,
    { timeout: 30000 },
  );
}

export async function run(ctx) {
  const { baseUrl, manifest, runner } = ctx;
  const history = manifest.history;

  // -- desktop: pinned history paragraph + two-tier person state -----------
  const page = await runner.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(historyUrl(baseUrl, history), { waitUntil: "domcontentloaded" });
  await page.waitForSelector(`.history-paragraph[data-unit-id="${history.paragraph_id}"]`, {
    timeout: 30000,
  });
  runner.check("history_paragraph_anchored", true);
  await waitPhaseReady(page, history.phase_id);
  runner.check("history_phase_ready_and_matches_version", true);
  runner.info("history_phase_id", history.phase_id);

  const entityRow = page
    .locator(`[data-test="reading-context-entity"][data-canonical="${history.entity_id}"]`)
    .first();
  await entityRow.waitFor({ timeout: 30000 });
  const facts = entityRow.locator(".chr-context-state");
  runner.check("person_state_fact_rendered_on_history", (await facts.count()) >= 1, "no state fact");
  const certainty = await facts.first().getAttribute("data-certainty");
  runner.check(
    "two_tier_marker_present",
    certainty === "clear" || certainty === "uncertain",
    `certainty=${certainty}`,
  );
  runner.info("state_certainty", certainty);
  await runner.screenshot(page, "history-desktop");

  // -- keyboard: focus the entity link and Enter navigates ---------------
  const viewLink = entityRow.locator('[data-test="reading-context-view-entity"]').first();
  await viewLink.focus();
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/entities\//, { timeout: 30000 });
  const phasePanel = page.locator('[data-test="entity-phase-state"]');
  await phasePanel.waitFor({ timeout: 30000 });
  const entityPhase = await phasePanel.getAttribute("data-phase-id");
  runner.check("person_page_phase_matches_history", entityPhase === history.phase_id, `${entityPhase}`);
  await runner.screenshot(page, "person-page-desktop");

  // -- in-place return, same version + paragraph --------------------------
  // A resolved return token renders the canonical "返回历史正文" link; the
  // no-token fallback renders the reading-enter control instead.
  const returnLink = page.getByRole("link", { name: "返回历史正文" });
  const hasReturn = (await returnLink.count()) >= 1;
  runner.check("person_page_offers_return", hasReturn, "no return control");
  await returnLink.first().click();
  await page.waitForURL(/\/history/, { timeout: 30000 });
  const returned = new URL(page.url());
  runner.check(
    "return_preserves_version_and_paragraph",
    returned.searchParams.get("version") === history.version &&
      returned.searchParams.get("at") === history.paragraph_id,
    page.url(),
  );

  // -- mobile: compact panel opens the same reviewed state ----------------
  const mobile = await runner.newPage({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
  });
  await mobile.goto(historyUrl(baseUrl, history), { waitUntil: "domcontentloaded" });
  await mobile.waitForSelector(`.history-paragraph[data-unit-id="${history.paragraph_id}"]`, {
    timeout: 30000,
  });
  const openPanel = mobile.locator('[data-test="reading-context-open"]');
  runner.check("mobile_context_entry_present", (await openPanel.count()) >= 1, "no compact entry");
  await openPanel.first().click();
  const mobilePanel = mobile.locator('[data-test="reading-context-panel"][data-variant="panel"]');
  await mobilePanel.waitFor({ timeout: 30000 });
  await mobilePanel.locator(`[data-test="reading-context-entity"][data-canonical="${history.entity_id}"]`).first()
    .waitFor({ timeout: 30000 });
  runner.check("mobile_person_state_visible", true);
  await runner.screenshot(mobile, "history-mobile");

  // The source-reading person route is proven over HTTP by the gate
  // (collect_source_person) and at component level by the registered
  // `person-states` suite, so the integrated suite stays on the third-round
  // terminal pages (composite HistoryPage + independent person page).
}

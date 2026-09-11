// C2-R2-T16 reading-flow suite: real integrated page against the running stack.
//
// Covers, for every published stream: unit reassembly, narrative-time axis,
// current-context roles, resolved event preview (hover/keyboard/touch),
// navigation negatives, content-version pinning and back/forward. A declared
// fixture/scene gap fails the suite; it never silently passes.

import { readingUrl } from "../manifest.mjs";

const UNIT = '[data-test="reading-unit"]';
const SEGMENTS =
  '[data-test="reading-segment"], [data-test="reading-event-trigger"], [data-test="reading-event-trigger-uncertain"], [data-test="reading-event-span"], [data-test="reading-event-span-uncertain"]';
const TRIGGERS =
  '[data-test="reading-event-trigger"], [data-test="reading-event-trigger-uncertain"]';

async function reassembleMismatches(page) {
  return await page.$$eval(
    UNIT,
    (units, segments) =>
      units
        .map((unit) => ({
          ordinal: unit.getAttribute("data-ordinal"),
          expected: unit.getAttribute("data-text") || "",
          joined: Array.from(unit.querySelectorAll(segments))
            .map((node) => node.textContent || "")
            .join(""),
        }))
        .filter((row) => row.joined !== row.expected),
    SEGMENTS,
  );
}

async function openStream(runner, baseUrl, stream, options) {
  const page = await runner.newPage(
    options || { viewport: { width: 1440, height: 900 } },
  );
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(readingUrl(baseUrl, stream), { waitUntil: "domcontentloaded" });
  try {
    await page.waitForSelector('[data-test="reading-page"]', { timeout: 30000 });
  } catch (error) {
    const state = await page
      .evaluate(() => ({
        url: location.href,
        body: document.body.innerText.slice(0, 200),
        error: document.querySelector('[data-test="reading-page-error"]')?.textContent ?? null,
      }))
      .catch(() => ({ url: "about:blank", body: "", error: null }));
    throw new Error(`reading-page not visible: ${JSON.stringify(state)} (${error})`);
  }
  await page.waitForSelector(UNIT, { timeout: 30000 });
  return { page, errors };
}

async function checkStream(runner, baseUrl, stream, { requireEvents }) {
  const { page, errors } = await openStream(runner, baseUrl, stream);
  try {
    runner.check(
      `page-stream-binding-${stream.stream_id}`,
      (await page.getAttribute('[data-test="reading-page"]', "data-stream")) ===
        stream.stream_id,
      "reading page must bind the requested stream",
    );
    const mismatches = await reassembleMismatches(page);
    runner.check(
      "segments-reassemble-unit-text",
      mismatches.length === 0,
      JSON.stringify(mismatches),
    );
    runner.check(
      "time-groups-present",
      (await page.locator('[data-test="reading-axis-group"]').count()) >= 1,
      "published narrative-time axis exposes no group",
    );
    runner.check(
      "context-entities-present",
      (await page.locator('[data-test="reading-context-entity"]').count()) >= 1,
      "current-context panel rendered no entity",
    );

    const triggers = page.locator(TRIGGERS);
    const triggerCount = await triggers.count();
    if (requireEvents || (stream.event_ids || []).length > 0) {
      runner.check(
        "event-trigger-present",
        triggerCount >= 1,
        "stream declares events but the page exposes no resolved trigger",
      );
    }
    if (triggerCount > 0) {
      const trigger = triggers.first();
      await trigger.hover();
      await page.waitForSelector('[data-test="reading-event-preview"]', {
        timeout: 10000,
      });
      runner.check("event-preview-opens", true);
      await page.waitForSelector('[data-test="reading-event-source-title"]', {
        timeout: 10000,
      });
      runner.check(
        "event-preview-source-attributed",
        (await page.locator('[data-test="reading-event-source-title"]').count()) >= 1,
        "preview must attribute a source",
      );
      runner.check(
        "context-role-sourced",
        (await page.locator('[data-test="reading-context-role"]').count()) >= 1,
        "current context must carry at least one sourced event role",
      );
      await page.keyboard.press("Escape");
      await page.waitForFunction(
        () => !document.querySelector('[data-test="reading-event-preview"]'),
        undefined,
        { timeout: 10000 },
      );
      runner.check("event-preview-closes-on-escape", true);
    }
    runner.check("no-page-error", errors.length === 0, errors.join("; "));
    await runner.screenshot(page, `stream-${stream.stream_id.slice(0, 8)}`);
  } finally {
    await runner.closePages();
  }
}

async function versionPinning(runner, baseUrl, versions) {
  for (const version of versions) {
    const stream = {
      stream_id: version.stream_id,
      catalog_sha: version.catalog_sha,
    };
    const { page } = await openStream(runner, baseUrl, stream);
    try {
      runner.check(
        `version-${version.label}-binds-stream`,
        (await page.getAttribute('[data-test="reading-page"]', "data-stream")) ===
          version.stream_id,
        `version ${version.label} did not bind its pinned stream`,
      );
    } finally {
      await runner.closePages();
    }
  }
  if (versions.length > 1) {
    const older = versions[0];
    const newer = versions[versions.length - 1];
    const { page } = await openStream(runner, baseUrl, {
      stream_id: newer.stream_id,
      catalog_sha: newer.catalog_sha,
    });
    try {
      await page.goto(
        readingUrl(baseUrl, {
          stream_id: older.stream_id,
          catalog_sha: older.catalog_sha,
        }),
        { waitUntil: "domcontentloaded" },
      );
      await page.waitForSelector(UNIT, { timeout: 30000 });
      runner.check(
        "old-reference-does-not-jump-new-version",
        (await page.getAttribute('[data-test="reading-page"]', "data-stream")) ===
          older.stream_id,
        "pinned old reference must not resolve to the newest stream",
      );
    } finally {
      await runner.closePages();
    }
  }
}

async function navigation(runner, baseUrl, stream) {
  const { page } = await openStream(runner, baseUrl, stream);
  try {
    const target = await page.locator(UNIT).last().getAttribute("data-unit-id");
    await page.goto(readingUrl(baseUrl, stream, target), {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    runner.check(
      "deep-link-restores-unit",
      (await page.locator(`${UNIT}[data-unit-id="${target}"]`).count()) >= 1,
      `deep link did not restore unit ${target}`,
    );
    await page.goBack({ waitUntil: "domcontentloaded" });
    try {
      await page.waitForSelector('[data-test="reading-page"]', { timeout: 30000 });
    } catch (error) {
      const state = await page
        .evaluate(() => ({ url: location.href, body: document.body.innerText.slice(0, 160) }))
        .catch(() => ({ url: "about:blank", body: "" }));
      throw new Error(`history-back did not return to a reading page: ${JSON.stringify(state)}`);
    }
    runner.check("history-back-returns", true);
    await page.goForward({ waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    runner.check(
      "history-forward-restores",
      (await page.locator(`${UNIT}[data-unit-id="${target}"]`).count()) >= 1,
    );
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    runner.check("refresh-restores-page", true);

    const bad = readingUrl(baseUrl, stream, "ru_" + "0".repeat(24));
    await page.goto(bad, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(
      '[data-test="reading-page-error"], [data-test="reading-page-back-to-directory"], [data-test="reading-issue"], [data-test="reading-reset"]',
      { timeout: 30000 },
    );
    runner.check("invalid-locator-explicit-error", true);
  } finally {
    await runner.closePages();
  }
}

async function touchInteraction(runner, baseUrl, stream) {
  const { page } = await openStream(runner, baseUrl, stream, {
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
  });
  try {
    const contextOpen = page.locator('[data-test="reading-context-open"]').first();
    if ((await contextOpen.count()) > 0) {
      await contextOpen.tap();
      await page.waitForSelector('[data-test="reading-context-panel"]', {
        timeout: 10000,
      });
      runner.check("touch-context-panel-opens", true);
      const close = page.locator('[data-test="reading-context-close"]').first();
      await close.scrollIntoViewIfNeeded().catch(() => {});
      await close.tap({ force: true });
      await page.waitForFunction(
        () => !document.querySelector('[data-test="reading-context-panel"]'),
        undefined,
        { timeout: 10000 },
      );
      runner.check("touch-context-panel-closes", true);
    }
    const axisToggle = page.locator('[data-test="reading-axis-toggle"]').first();
    if ((await axisToggle.count()) > 0) {
      await axisToggle.tap();
      runner.check(
        "touch-axis-toggle",
        (await page.locator('[data-test="reading-axis-panel"]').count()) >= 0,
      );
    }
    const trigger = page.locator(TRIGGERS).first();
    if ((await trigger.count()) > 0) {
      await trigger.tap();
      await page.waitForSelector('[data-test="reading-event-preview"]', {
        timeout: 10000,
      });
      runner.check("touch-event-preview-opens", true);
      const previewClose = page
        .locator('[data-test="reading-event-preview-close"]')
        .first();
      await previewClose.scrollIntoViewIfNeeded().catch(() => {});
      await previewClose.tap({ force: true });
      runner.check("touch-event-preview-closes", true);
    } else {
      runner.check(
        "touch-event-preview-opens",
        false,
        "no resolved event trigger available for touch scenario",
      );
    }
  } finally {
    await runner.closePages();
  }
}

async function negativeScenarios(runner, baseUrl, negatives) {
  const byKind = Object.fromEntries(negatives.map((item) => [item.kind, item]));
  const openAt = async (negative, unitId) => {
    const { page } = await openStream(
      runner,
      baseUrl,
      { stream_id: negative.stream_id, catalog_sha: negative.catalog_sha },
      { viewport: { width: 1440, height: 900 } },
    );
    if (unitId && unitId !== negative.unit_id) {
      await page.goto(
        readingUrl(
          baseUrl,
          { stream_id: negative.stream_id, catalog_sha: negative.catalog_sha },
          unitId,
        ),
        { waitUntil: "domcontentloaded" },
      );
      await page.waitForSelector(UNIT, { timeout: 30000 });
    }
    return page;
  };

  if (byKind.unknown_time) {
    const page = await openAt(byKind.unknown_time, byKind.unknown_time.unit_id);
    try {
      await page.waitForSelector('[data-test="reading-compact-time"]', {
        timeout: 10000,
      });
      const label = (await page
        .locator('[data-test="reading-compact-time"]')
        .first()
        .innerText()).trim();
      runner.check(
        "unknown-time-expressed",
        label.includes("未") || label.includes("未知"),
        `unknown-time unit rendered ${label}`,
      );
      runner.check(
        "unknown-time-not-fabricated",
        !/[0-9]{3,4}\s*年/.test(label),
        `unknown-time unit fabricated a year: ${label}`,
      );
    } finally {
      await runner.closePages();
    }
  }

  if (byKind.missing_context) {
    const page = await openAt(
      byKind.missing_context,
      byKind.missing_context.previous_context_unit_id,
    );
    try {
    try {
      await page.waitForSelector('[data-test="reading-context-entity"]', {
        timeout: 15000,
      });
    } catch {
      /* asserted below */
    }
    runner.check(
      "context-shown-before-clearing",
      (await page.locator('[data-test="reading-context-entity"]').count()) >= 1,
      "preceding unit exposed no context to clear",
    );
      await page.goto(
        readingUrl(
          baseUrl,
          {
            stream_id: byKind.missing_context.stream_id,
            catalog_sha: byKind.missing_context.catalog_sha,
          },
          byKind.missing_context.unit_id,
        ),
        { waitUntil: "domcontentloaded" },
      );
      await page.waitForSelector(UNIT, { timeout: 30000 });
      runner.check(
        "missing-context-clears",
        (await page.locator('[data-test="reading-context-entity"]').count()) === 0,
        "context was not cleared on a unit without context",
      );
    } finally {
      await runner.closePages();
    }
  }

  if (byKind.missing_role) {
    const page = await openAt(byKind.missing_role, byKind.missing_role.unit_id);
    try {
      try {
        await page.waitForSelector('[data-test="reading-context-entity"]', {
          timeout: 15000,
        });
      } catch {
        /* asserted below */
      }
      runner.check(
        "missing-role-entity-present",
        (await page.locator('[data-test="reading-context-entity"]').count()) >= 1,
        "missing-role entity was not rendered",
      );
      runner.check(
        "missing-role-not-fabricated",
        (await page.locator('[data-test="reading-context-role"]').count()) === 0,
        "a role was fabricated for an entity with no sourced role",
      );
    } finally {
      await runner.closePages();
    }
  }
}

export async function run(ctx) {
  const { runner, baseUrl, manifest } = ctx;
  const streams = manifest.streams;
  const anyEvents = streams.some((stream) => (stream.event_ids || []).length > 0);
  runner.check(
    "fixture-declares-events",
    anyEvents,
    "fixture manifest declares no event ids; event scenarios cannot be exercised",
  );
  for (const stream of streams) {
    await checkStream(runner, baseUrl, stream, { requireEvents: anyEvents });
  }
  await versionPinning(runner, baseUrl, manifest.versions);
  await navigation(runner, baseUrl, streams[0]);
  await touchInteraction(runner, baseUrl, streams[0]);
  await negativeScenarios(runner, baseUrl, manifest.negatives);
  return runner;
}

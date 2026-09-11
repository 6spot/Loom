// C2-R2-T16 reading-flow suite: real integrated page against the running stack.

import { readingUrl } from "../manifest.mjs";

const UNIT = '[data-test="reading-unit"]';
const SEGMENTS =
  '[data-test="reading-segment"], [data-test="reading-event-span"], [data-test="reading-event-span-uncertain"]';

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

async function openStream(runner, baseUrl, stream) {
  const page = await runner.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(readingUrl(baseUrl, stream), { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-test="reading-page"]', { timeout: 30000 });
  await page.waitForSelector(UNIT, { timeout: 30000 });
  runner.check(
    "page-stream-binding",
    (await page.getAttribute('[data-test="reading-page"]', "data-stream")) === stream.stream_id,
    "reading page must bind the requested stream",
  );
  runner.check(
    "page-renders-units",
    (await page.locator(UNIT).count()) >= 1,
    "reading page rendered no units",
  );
  const mismatches = await reassembleMismatches(page);
  runner.check(
    "segments-reassemble-unit-text",
    mismatches.length === 0,
    JSON.stringify(mismatches),
  );
  runner.info("units_rendered", await page.locator(UNIT).count());
  await runner.screenshot(page, "stream");
  return { page, errors };
}

async function scrollAndFollow(runner, page) {
  const before = await page
    .locator(`${UNIT}[data-active="true"]`)
    .first()
    .getAttribute("data-ordinal");
  await page.mouse.wheel(0, 2600);
  await page.waitForFunction(
    (previous) => {
      const active = document.querySelector('[data-test="reading-unit"][data-active="true"]');
      return active && active.getAttribute("data-ordinal") !== previous;
    },
    before,
    { timeout: 15000 },
  );
  runner.check("scroll-updates-active-unit", true);
  runner.check(
    "compact-bar-reflects-active",
    (await page.locator('[data-test="reading-compact-time"]').count()) >= 1,
    "compact bar missing after scroll",
  );
}

async function eventPreview(runner, page) {
  const trigger = page
    .locator('[data-test="reading-event-trigger"], [data-test="reading-event-trigger-uncertain"]')
    .first();
  if ((await trigger.count()) === 0) {
    runner.check(
      "event-trigger-present",
      false,
      "published stream exposes no event trigger to exercise",
    );
  }
  await trigger.hover();
  await page.waitForSelector('[data-test="reading-event-preview"]', { timeout: 10000 });
  runner.check("event-preview-opens", true);
  await page.keyboard.press("Escape");
  await page.waitForFunction(
    () => !document.querySelector('[data-test="reading-event-preview"]'),
    undefined,
    { timeout: 10000 },
  );
  runner.check("event-preview-closes-on-escape", true);
}

async function navigation(runner, page, baseUrl, stream) {
  const target = await page.locator(UNIT).first().getAttribute("data-unit-id");
  const deep = readingUrl(baseUrl, stream, target);
  await page.goto(deep, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(UNIT, { timeout: 30000 });
  runner.check(
    "deep-link-restores-unit",
    (await page.locator(`${UNIT}[data-unit-id="${target}"]`).count()) >= 1,
    `deep link did not restore unit ${target}`,
  );
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector(UNIT, { timeout: 30000 });
  runner.check("refresh-restores-page", true);
  const bad = readingUrl(baseUrl, { ...stream, stream_id: stream.stream_id }, "ru_" + "0".repeat(24));
  await page.goto(bad, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(
    '[data-test="reading-page-error"], [data-test="reading-page-back-to-directory"]',
    { timeout: 30000 },
  );
  runner.check("invalid-locator-explicit-error", true);
}

export async function run(ctx) {
  const { runner, baseUrl, manifest } = ctx;
  const stream = manifest.streams[0];
  const { page, errors } = await openStream(runner, baseUrl, stream);
  try {
    runner.check(
      "axis-or-compact-present",
      (await page.locator('[data-test="reading-time-axis"]').count()) +
        (await page.locator('[data-test="reading-compact-bar"]').count()) >=
        1,
      "reading page exposes neither the time axis nor the compact bar",
    );
    runner.check(
      "time-groups-present",
      (await page.locator('[data-test="reading-axis-group"]').count()) >= 1,
      "published narrative-time axis exposes no group",
    );
    await scrollAndFollow(runner, page);
    await eventPreview(runner, page);
    await navigation(runner, page, baseUrl, stream);
    runner.check("no-page-error", errors.length === 0, errors.join("; "));
  } finally {
    await runner.closePages();
  }
  return runner;
}

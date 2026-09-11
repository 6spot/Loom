// C2-R2-T16 accessibility/layout suite: real viewports, keyboard, reduced motion.

import { readingUrl, viewports } from "../manifest.mjs";

const UNIT = '[data-test="reading-unit"]';

async function horizontalOverflow(page) {
  return await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
}

// Body-text overflow at 200% is scoped to the reading main column: the global
// public chrome (site header/search) is not owned by the reading page.
async function readingOverflow(page) {
  return await page.evaluate(() => {
    const main = document.querySelector('[data-test="reading-main"]') || document.querySelector(".rpage");
    if (!main) return 0;
    return main.scrollWidth - main.clientWidth;
  });
}

async function openAt(runner, baseUrl, stream, viewport) {
  const page = await runner.newPage({
    viewport: { width: viewport.width, height: viewport.height },
  });
  await page.goto(readingUrl(baseUrl, stream), { waitUntil: "domcontentloaded" });
  await page.waitForSelector(UNIT, { timeout: 30000 });
  return page;
}

async function fontScaling(runner, baseUrl, stream) {
  for (const viewport of [
    { width: 1440, height: 900, name: "desktop" },
    { width: 390, height: 844, name: "mobile" },
  ]) {
    const page = await openAt(runner, baseUrl, stream, viewport);
    try {
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      await page.waitForTimeout(300);
      runner.check(
        `font-200-no-horizontal-overflow-${viewport.name}`,
        (await readingOverflow(page)) <= 1,
        `200% font size produced horizontal reading-body overflow at ${viewport.name}`,
      );
      runner.check(
        `font-200-keeps-units-${viewport.name}`,
        (await page.locator(UNIT).count()) >= 1,
      );
      await runner.screenshot(page, `font-200-${viewport.name}`);
    } finally {
      await runner.closePages();
    }
  }
}

async function keyboardFlow(runner, baseUrl, stream) {
  const page = await openAt(runner, baseUrl, stream, { width: 1440, height: 900 });
  try {
    const trigger = page
      .locator('[data-test="reading-event-trigger"], [data-test="reading-event-trigger-uncertain"]')
      .first();
    runner.check("keyboard-trigger-present", (await trigger.count()) >= 1);
    await trigger.focus();
    runner.check("keyboard-focus-visible", await trigger.evaluate((node) => node === document.activeElement));
    await page.keyboard.press("Enter");
    await page.waitForSelector('[data-test="reading-event-preview"]', { timeout: 10000 });
    runner.check("keyboard-preview-opens", true);
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector('[data-test="reading-event-preview"]'),
      undefined,
      { timeout: 10000 },
    );
    runner.check("keyboard-preview-closes", true);
  } finally {
    await runner.closePages();
  }
}

async function reducedMotion(runner, baseUrl, stream) {
  const page = await openAt(runner, baseUrl, stream, { width: 1440, height: 900 });
  try {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const trigger = page
      .locator('[data-test="reading-event-trigger"], [data-test="reading-event-trigger-uncertain"]')
      .first();
    runner.check(
      "reduced-motion-trigger-present",
      (await trigger.count()) >= 1,
      "no resolved event trigger available for the reduced-motion scenario",
    );
    await trigger.hover();
    await page.waitForSelector('[data-test="reading-event-preview"]', { timeout: 10000 });
    runner.check("reduced-motion-preview-works", true);
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector('[data-test="reading-event-preview"]'),
      undefined,
      { timeout: 10000 },
    );
    runner.check("reduced-motion-preview-closes", true);
  } finally {
    await runner.closePages();
  }
}

async function targetSizes(runner, page) {
  const controls = ['[data-test="reading-axis-toggle"]', '[data-test="reading-context-open"]'];
  let measured = 0;
  for (const selector of controls) {
    const locator = page.locator(selector).first();
    if ((await locator.count()) === 0) continue;
    const box = await locator.boundingBox();
    if (!box) continue;
    measured += 1;
    runner.check(
      `target-size-${selector}`,
      box.width >= 44 && box.height >= 44,
      `${selector} is ${box.width}x${box.height}, expected >=44x44`,
    );
  }
  runner.info("targets_measured", measured);
}

async function contrast(runner, page) {
  const result = await page.evaluate(() => {
    const text = document.querySelector('[data-test="reading-unit-text"]');
    if (!text) return null;
    const parse = (value) => {
      const match = value.match(/rgba?\(([^)]+)\)/);
      if (!match) return null;
      const parts = match[1].split(",").map((item) => parseFloat(item.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
    };
    const luminance = (c) => {
      const channel = (v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
    };
    const foreground = parse(getComputedStyle(text).color);
    let node = text;
    let background = null;
    while (node && !background) {
      const candidate = parse(getComputedStyle(node).backgroundColor);
      if (candidate && candidate.a > 0.99) background = candidate;
      node = node.parentElement;
    }
    if (!foreground || !background) return null;
    const light = Math.max(luminance(foreground), luminance(background));
    const dark = Math.min(luminance(foreground), luminance(background));
    return (light + 0.05) / (dark + 0.05);
  });
  if (result === null) {
    runner.check("body-contrast-measurable", false, "could not resolve body text/background");
    return;
  }
  runner.info("body_contrast_ratio", Number(result.toFixed(2)));
  runner.check("body-contrast-wcag-aa", result >= 4.5, `ratio=${result.toFixed(2)} < 4.5`);
}

export async function run(ctx) {
  const { runner, baseUrl, manifest } = ctx;
  const stream = manifest.streams[0];
  for (const viewport of viewports(manifest)) {
    const page = await openAt(runner, baseUrl, stream, viewport);
    try {
      runner.check(
        `no-horizontal-overflow-${viewport.name}`,
        (await horizontalOverflow(page)) <= 1,
        `${viewport.name} produced horizontal body overflow`,
      );
      runner.check(`units-present-${viewport.name}`, (await page.locator(UNIT).count()) >= 1);
      await runner.screenshot(page, viewport.name);
      await targetSizes(runner, page);
    } finally {
      await runner.closePages();
    }
  }
  await fontScaling(runner, baseUrl, stream);
  await keyboardFlow(runner, baseUrl, stream);
  await reducedMotion(runner, baseUrl, stream);
  const contrastPage = await openAt(runner, baseUrl, stream, { width: 1440, height: 900 });
  try {
    await contrast(runner, contrastPage);
  } finally {
    await runner.closePages();
  }
  return runner;
}

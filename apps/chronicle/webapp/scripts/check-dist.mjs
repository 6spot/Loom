#!/usr/bin/env node
// Post-build gate: exactly one Vite build must serve both public and Studio
// routes, with deterministic filenames the Rust server embeds.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const dist = new URL("../../web/dist/", import.meta.url).pathname;
const failures = [];

const required = ["index.html", "assets/index.js", "assets/index.css"];
for (const file of required) {
  if (!existsSync(join(dist, file))) failures.push(`missing dist/${file}`);
}

if (existsSync(join(dist, "index.html"))) {
  const shell = readFileSync(join(dist, "index.html"), "utf-8");
  if (!shell.includes("Chronicle")) failures.push("dist shell mentions Chronicle");
  if (!shell.includes('id="root"')) failures.push("dist shell has #root mount");
  if (!shell.includes("/assets/index.js") && !shell.includes("assets/index.js"))
    failures.push("dist shell loads the public entry");
}

if (existsSync(join(dist, "assets"))) {
  const assets = readdirSync(join(dist, "assets"));
  const hasStudioChunk = assets.some((name) => /studio|StudioLayout|placeholders/i.test(name));
  if (!hasStudioChunk) failures.push("dist/assets has no route-split Studio chunk");
  const hashed = assets.filter((name) => /-[0-9a-f]{6,}\./.test(name));
  if (hashed.length > 0) failures.push(`dist/assets must use deterministic names for compile-time embed: ${hashed.join(", ")}`);
} else {
  failures.push("missing dist/assets");
}

if (failures.length > 0) {
  console.error(`chronicle webapp dist check: FAIL\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log("chronicle webapp dist check: PASS");

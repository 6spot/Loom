import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Frontend authority guard: browser code must stay downstream of HTTP APIs.
// It must not import database drivers, touch the filesystem/ORM layer, read
// staged artifacts or migrations, or embed deployment secrets.
const FORBIDDEN = [
  "CHRONICLE_DATABASE_URL",
  "psycopg",
  "sqlx",
  "tokio-postgres",
  "postgres",
  ".artifacts",
  "migrations/",
  "apps/chronicle/persistence",
  "apps/chronicle/ingestion",
  "require(\"fs\")",
  'require("node:fs")',
  'from "node:fs"',
  "process.env",
];

const ALLOWLISTED_FILES = new Set(["no-db-authority.test.ts"]);

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === "dist") continue;
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx|css|html)$/.test(entry)) out.push(full);
  }
  return out;
}

describe("no direct DB/artifact authority in frontend code", () => {
  it("scans every webapp source file", () => {
    const root = new URL("..", import.meta.url).pathname;
    const files = sources(join(root, "src")).concat(
      [join(root, "index.html"), join(root, "package.json"), join(root, "vite.config.ts")].filter((file) => {
        try {
          statSync(file);
          return true;
        } catch {
          return false;
        }
      }),
    );
    expect(files.length).toBeGreaterThan(10);
    const violations: string[] = [];
    for (const file of files) {
      const name = file.split("/").pop() ?? file;
      if (ALLOWLISTED_FILES.has(name)) continue;
      const content = readFileSync(file, "utf-8");
      for (const needle of FORBIDDEN) {
        if (content.includes(needle)) violations.push(`${file}: ${needle}`);
      }
    }
    expect(violations).toEqual([]);
  });
});

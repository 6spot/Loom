import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// Route-split guard: public entry modules must not eagerly import the Studio
// surface. Studio routes load through React.lazy in App.tsx so ordinary
// public navigation never needs the admin component surface.
describe("studio code is route-split from public navigation", () => {
  it("App.tsx lazy-loads every studio route", () => {
    const root = new URL("..", import.meta.url).pathname;
    const app = readFileSync(`${root}src/App.tsx`, "utf-8");
    for (const module of [
      "./pages/studio/StudioLayout",
      "./pages/studio/StudioHomePage",
      "./pages/studio/StudioLoginPage",
      "./pages/studio/placeholders",
    ]) {
      expect(app).toContain(`lazy(() => import("${module}")`);
    }
    expect(app.includes("lazy(")).toBe(true);
  });

  it("public pages never import the shadcn studio foundation", () => {
    const root = new URL("..", import.meta.url).pathname;
    const publicPages = ["TimelinePage.tsx", "EventPage.tsx", "EntityPage.tsx", "SearchPage.tsx"];
    for (const page of publicPages) {
      const content = readFileSync(`${root}src/pages/public/${page}`, "utf-8");
      expect(content).not.toContain("components/ui");
      expect(content).not.toContain("studio.css");
    }
  });
});

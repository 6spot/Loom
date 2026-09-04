// Shared public presentation helpers (ported from C0 web/ui.mjs so the
// React migration keeps byte-level DOM contracts the browser smoke relies
// on: data-event-id, data-view, data-test hooks, and zh-CN section labels).

export function escapeHTML(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

export function formatYear(year: number | null | undefined): string {
  if (year === null || year === undefined || Number.isNaN(Number(year))) return "年代未定";
  const value = Number(year);
  return value < 0 ? `公元前 ${Math.abs(value)} 年` : `公元 ${value} 年`;
}

export function formatTime(time: { start_year?: number | null; end_year?: number | null } = {}): string {
  const start = time.start_year;
  const end = time.end_year;
  if (start === null || start === undefined || end === null || end === undefined) return "年代未定";
  if (start === end) return formatYear(start);
  return `${formatYear(start)} — ${formatYear(end)}`;
}

export type PublicRoute =
  | { view: "timeline"; id: null }
  | { view: "event"; id: string }
  | { view: "entity"; id: string }
  | { view: "search"; id: null }
  | { view: "not_found"; id: null };

export function routeFor(pathname: string): PublicRoute {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/" || path === "/timeline") return { view: "timeline", id: null };
  if (path === "/search") return { view: "search", id: null };
  const event = path.match(/^\/events\/([^/]+)$/);
  if (event) return { view: "event", id: decodeURIComponent(event[1]) };
  const entity = path.match(/^\/entities\/([^/]+)$/);
  if (entity) return { view: "entity", id: decodeURIComponent(entity[1]) };
  return { view: "not_found", id: null };
}

export function safeRouteFor(pathname: string): PublicRoute {
  try {
    return routeFor(pathname);
  } catch (error) {
    if (error instanceof URIError) return { view: "not_found", id: null };
    throw error;
  }
}

export function isStudioPath(pathname: string): boolean {
  return pathname === "/studio" || pathname.startsWith("/studio/");
}

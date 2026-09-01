import { routeFor } from "./ui.mjs";

export function safeRouteFor(pathname) {
  try {
    const path = pathname.replace(/\/+$/, "") || "/";
    if (path === "/search") return { view: "search", id: null };
    return routeFor(pathname);
  } catch (error) {
    if (error instanceof URIError) {
      return { view: "not_found", id: null };
    }
    throw error;
  }
}

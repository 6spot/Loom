import { routeFor } from "./ui.mjs";

export function safeRouteFor(pathname) {
  try {
    return routeFor(pathname);
  } catch (error) {
    if (error instanceof URIError) {
      return { view: "not_found", id: null };
    }
    throw error;
  }
}

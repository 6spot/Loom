import {
  renderEntity,
  renderError,
  renderEvent,
  renderLoading,
  renderNotFound,
  renderTimeline,
  timelineApiPath,
} from "/ui.mjs";
import { renderSearch, renderSearchEmpty, searchApiPath } from "/search_ui.mjs";
import { safeRouteFor } from "/route_safe.mjs";

const app = document.querySelector("#app");
const globalSearch = document.querySelector("#global-search-q");

async function fetchJSON(path) {
  const response = await fetch(path, {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw { code: "invalid_response", message: `Chronicle API returned HTTP ${response.status}` };
  }

  if (!response.ok) {
    throw payload?.error ?? { code: "request_failed", message: `Chronicle API returned HTTP ${response.status}` };
  }
  return payload;
}

function titleFor(route, payload) {
  if (route.view === "event") return `${payload?.display?.title ?? "事件"} · Chronicle`;
  if (route.view === "entity") return `${payload?.display?.name ?? "实体"} · Chronicle`;
  if (route.view === "search") {
    const q = payload?.query?.q ?? new URLSearchParams(window.location.search).get("q") ?? "";
    return q ? `${q} · 搜索 · Chronicle` : "搜索 · Chronicle";
  }
  return "Chronicle · 历史时间线";
}

async function load() {
  const route = safeRouteFor(window.location.pathname);
  if (route.view === "not_found") {
    app.innerHTML = renderNotFound();
    document.title = "页面不存在 · Chronicle";
    return;
  }

  const searchParams = new URLSearchParams(window.location.search);
  const searchQuery = (searchParams.get("q") ?? "").trim();
  if (globalSearch && route.view === "search") globalSearch.value = searchQuery;

  if (route.view === "search" && !searchQuery) {
    app.innerHTML = renderSearchEmpty();
    document.title = titleFor(route, null);
    return;
  }

  app.innerHTML = renderLoading(
    route.view === "timeline" ? "时间线" : route.view === "event" ? "事件" : route.view === "entity" ? "实体" : "搜索结果"
  );

  try {
    let payload;
    if (route.view === "timeline") {
      payload = await fetchJSON(timelineApiPath(window.location.search));
      app.innerHTML = renderTimeline(payload);
    } else if (route.view === "event") {
      payload = await fetchJSON(`/v0/events/${encodeURIComponent(route.id)}`);
      app.innerHTML = renderEvent(payload);
    } else if (route.view === "entity") {
      payload = await fetchJSON(`/v0/entities/${encodeURIComponent(route.id)}`);
      app.innerHTML = renderEntity(payload);
    } else {
      payload = await fetchJSON(searchApiPath(window.location.search));
      app.innerHTML = renderSearch(payload);
    }
    document.title = titleFor(route, payload);
  } catch (error) {
    app.innerHTML = renderError(error);
    document.title = "读取失败 · Chronicle";
  }
}

load();

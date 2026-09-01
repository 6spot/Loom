import {
  renderEntity,
  renderError,
  renderEvent,
  renderLoading,
  renderNotFound,
  renderTimeline,
  routeFor,
  timelineApiPath,
} from "/ui.mjs";

const app = document.querySelector("#app");

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
  return "Chronicle · 历史时间线";
}

async function load() {
  const route = routeFor(window.location.pathname);
  if (route.view === "not_found") {
    app.innerHTML = renderNotFound();
    document.title = "页面不存在 · Chronicle";
    return;
  }

  app.innerHTML = renderLoading(
    route.view === "timeline" ? "时间线" : route.view === "event" ? "事件" : "实体"
  );

  try {
    let payload;
    if (route.view === "timeline") {
      payload = await fetchJSON(timelineApiPath(window.location.search));
      app.innerHTML = renderTimeline(payload);
    } else if (route.view === "event") {
      payload = await fetchJSON(`/v0/events/${encodeURIComponent(route.id)}`);
      app.innerHTML = renderEvent(payload);
    } else {
      payload = await fetchJSON(`/v0/entities/${encodeURIComponent(route.id)}`);
      app.innerHTML = renderEntity(payload);
    }
    document.title = titleFor(route, payload);
  } catch (error) {
    app.innerHTML = renderError(error);
    document.title = "读取失败 · Chronicle";
  }
}

load();

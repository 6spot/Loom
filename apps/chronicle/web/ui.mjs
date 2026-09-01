const HTML_ESCAPE = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => HTML_ESCAPE[char]);
}

function safeJSON(value) {
  return escapeHTML(JSON.stringify(value ?? {}, null, 2));
}

export function formatYear(year) {
  if (year === null || year === undefined || Number.isNaN(Number(year))) return "年代未定";
  const value = Number(year);
  return value < 0 ? `公元前 ${Math.abs(value)} 年` : `公元 ${value} 年`;
}

export function formatTime(time = {}) {
  const start = time.start_year;
  const end = time.end_year;
  if (start === null || start === undefined || end === null || end === undefined) return "年代未定";
  if (start === end) return formatYear(start);
  return `${formatYear(start)} — ${formatYear(end)}`;
}

export function routeFor(pathname) {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/" || path === "/timeline") return { view: "timeline", id: null };
  const event = path.match(/^\/events\/([^/]+)$/);
  if (event) return { view: "event", id: decodeURIComponent(event[1]) };
  const entity = path.match(/^\/entities\/([^/]+)$/);
  if (entity) return { view: "entity", id: decodeURIComponent(entity[1]) };
  return { view: "not_found", id: null };
}

export function timelineApiPath(search = "") {
  const incoming = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const outgoing = new URLSearchParams();
  for (const key of ["from_year", "to_year", "limit", "offset"]) {
    const value = incoming.get(key);
    if (value !== null && value !== "") outgoing.set(key, value);
  }
  if (!outgoing.has("limit")) outgoing.set("limit", "50");
  if (!outgoing.has("offset")) outgoing.set("offset", "0");
  return `/v0/timeline?${outgoing.toString()}`;
}

function eventHref(id) {
  return `/events/${encodeURIComponent(id)}`;
}

function entityHref(id) {
  return `/entities/${encodeURIComponent(id)}`;
}

function typeChip(type) {
  return type ? `<span class="chip type">${escapeHTML(type)}</span>` : "";
}

function sourceChips(titles = []) {
  return titles.map((title) => `<span class="source-chip">${escapeHTML(title)}</span>`).join("");
}

function detailsJSON(label, payload) {
  return `<details class="details-json"><summary>${escapeHTML(label)}</summary><pre>${safeJSON(payload)}</pre></details>`;
}

function claimCard(wrapper) {
  const claim = wrapper?.claim ?? {};
  const evidence = claim.evidence ?? {};
  const predicate = claim.predicate ?? "claim";
  const evidenceText = evidence.text ?? "（此 Claim 没有 evidence.text）";
  const locator = evidence.locator && Object.keys(evidence.locator).length
    ? `<div class="locator">定位：${escapeHTML(JSON.stringify(evidence.locator))}</div>`
    : "";
  return `<article class="claim" data-test="claim">
    <div class="predicate">${escapeHTML(predicate)} · ${escapeHTML(wrapper?.bundle ?? "")} : ${escapeHTML(wrapper?.ref ?? "")}</div>
    <blockquote>${escapeHTML(evidenceText)}</blockquote>
    ${locator}
  </article>`;
}

function claimsBlock(claims = []) {
  if (!claims.length) return `<p class="muted">此记录没有直接关联的 Claim。</p>`;
  return `<div class="claims-list">${claims.map(claimCard).join("")}</div>`;
}

const DECISION_LABEL = {
  same_entity: "同一实体",
  same_occurrence: "同一事件",
  related_occurrence: "相关但不同事件",
  uncertain: "身份不确定",
  not_same: "明确不同",
};

function decisionBadge(decision) {
  return `<span class="decision ${escapeHTML(decision ?? "")}">${escapeHTML(DECISION_LABEL[decision] ?? decision ?? "unknown")}</span>`;
}

function resolutionItem(link, targetKind, currentId) {
  const confidence = Number.isFinite(Number(link.confidence)) ? `${Math.round(Number(link.confidence) * 100)}%` : "—";
  const sideKey = targetKind === "entity" ? "canonical_entity_id" : "canonical_event_id";
  const leftId = link.left?.[sideKey] ?? null;
  const rightId = link.right?.[sideKey] ?? null;
  const otherId = leftId && leftId !== currentId ? leftId : rightId && rightId !== currentId ? rightId : null;
  const otherLink = otherId
    ? `<a href="${targetKind === "entity" ? entityHref(otherId) : eventHref(otherId)}">查看另一 canonical ${targetKind === "entity" ? "Entity" : "Event"}</a>`
    : "";
  return `<article class="resolution-item" data-decision="${escapeHTML(link.decision ?? "")}">
    <header>${decisionBadge(link.decision)}<span class="count">confidence ${escapeHTML(confidence)}</span></header>
    <p>${escapeHTML(link.rationale ?? "无 rationale")}</p>
    ${otherLink}
    ${detailsJSON("Resolution signals", link.signals ?? {})}
  </article>`;
}

function resolutionBlock(links = [], targetKind, currentId) {
  if (!links.length) return `<p class="muted">没有跨来源 Resolution 记录。</p>`;
  return `<div class="resolution-list">${links.map((link) => resolutionItem(link, targetKind, currentId)).join("")}</div>`;
}

function paginationHref(query = {}, offset) {
  const params = new URLSearchParams();
  for (const key of ["from_year", "to_year"]) {
    if (query[key] !== null && query[key] !== undefined) params.set(key, String(query[key]));
  }
  params.set("limit", String(query.limit ?? 50));
  params.set("offset", String(Math.max(0, offset)));
  return `/timeline?${params.toString()}`;
}

export function renderTimeline(data) {
  const items = data?.items ?? [];
  const query = data?.query ?? {};
  const page = data?.page ?? { total: items.length, returned: items.length, has_more: false };
  const from = query.from_year ?? "";
  const to = query.to_year ?? "";
  const cards = items.map((item) => `<article class="timeline-card" data-event-id="${escapeHTML(item.canonical_event_id)}">
    <div class="timeline-year">${escapeHTML(formatTime(item.time))}</div>
    <h2><a href="${eventHref(item.canonical_event_id)}">${escapeHTML(item.display?.title ?? "未命名事件")}</a></h2>
    <div class="hero-meta">
      ${typeChip(item.display?.type)}
      <span class="chip">${escapeHTML(item.source_count ?? 0)} 个来源</span>
      <span class="chip">${escapeHTML(item.representation_count ?? 0)} 条记录</span>
    </div>
    <div class="source-list">${sourceChips(item.source_titles ?? [])}</div>
  </article>`).join("");

  const offset = Number(query.offset ?? 0);
  const limit = Number(query.limit ?? 50);
  const previous = offset > 0 ? `<a rel="prev" href="${paginationHref(query, offset - limit)}">← 上一页</a>` : "";
  const next = page.has_more ? `<a rel="next" href="${paginationHref(query, offset + limit)}">下一页 →</a>` : "";

  return `<section data-view="timeline">
    <header class="page-header">
      <p class="eyebrow">Timeline</p>
      <h1>历史时间线</h1>
      <p class="lede">每张卡片代表一个 canonical Event。多个史料描述同一 occurrence 时只出现一次，来源与证据在详情页继续展开。</p>
    </header>

    <form class="filter-panel" action="/timeline" method="get">
      <div class="field"><label for="from_year">起始年份</label><input id="from_year" name="from_year" inputmode="numeric" value="${escapeHTML(from)}" placeholder="例如 208"></div>
      <div class="field"><label for="to_year">结束年份</label><input id="to_year" name="to_year" inputmode="numeric" value="${escapeHTML(to)}" placeholder="例如 220"></div>
      <button class="primary-button" type="submit">查看时间段</button>
    </form>

    <div class="page-stats"><span>共 ${escapeHTML(page.total ?? items.length)} 个 canonical Events</span><span>本页 ${escapeHTML(page.returned ?? items.length)} 个</span></div>
    ${items.length ? `<div class="timeline-list">${cards}</div>` : `<section class="state-card empty-card"><h2>这个时间段还没有已收录事件</h2><p class="muted">缺少数据不等于历史上什么都没有发生。</p></section>`}
    ${(previous || next) ? `<nav class="pagination" aria-label="时间线分页">${previous}${next}</nav>` : ""}
  </section>`;
}

function linkedEntity(item, sourceLabel) {
  const name = item.display?.name ?? "未命名实体";
  const type = item.display?.type ?? "entity";
  if (!item.canonical_entity_id) {
    return `<div class="entity-link"><span><strong>${escapeHTML(name)}</strong><small> · ${escapeHTML(type)}</small></span><span class="decision uncertain">未解析</span></div>`;
  }
  return `<a class="entity-link" href="${entityHref(item.canonical_entity_id)}" data-test="entity-link">
    <span><strong>${escapeHTML(name)}</strong><small> · ${escapeHTML(type)}</small></span>
    <span class="muted">${escapeHTML(sourceLabel)}</span>
  </a>`;
}

function eventRepresentation(rep) {
  return `<article class="source-card" data-source="${escapeHTML(rep.bundle)}">
    <header><div><div class="source-title">${escapeHTML(rep.source?.title ?? rep.bundle)}</div><div class="muted">Source representation</div></div><code>${escapeHTML(rep.bundle)}:${escapeHTML(rep.ref)}</code></header>
    ${claimsBlock(rep.claims ?? [])}
    ${detailsJSON("查看源 Event 记录", rep.event ?? {})}
    ${detailsJSON("查看 Source 元数据", rep.source?.record ?? {})}
  </article>`;
}

export function renderEvent(data) {
  const participants = data?.participants ?? [];
  const places = data?.places ?? [];
  const related = data?.related_events ?? [];
  const reps = data?.representations ?? [];
  const relatedCards = related.map((item) => `<a class="related-card" href="${eventHref(item.event.canonical_event_id)}" data-test="related-event">
    <strong>${escapeHTML(item.event.display?.title ?? "未命名事件")}</strong>
    <span class="muted">${escapeHTML(formatTime(item.event.time))} · ${escapeHTML(DECISION_LABEL[item.type] ?? item.type)}</span>
  </a>`).join("");

  return `<section data-view="event" data-canonical-id="${escapeHTML(data.canonical_event_id)}">
    <div class="breadcrumbs"><a href="/timeline">时间线</a><span>›</span><span>事件</span></div>
    <header class="page-header">
      <p class="eyebrow">Canonical Event</p>
      <h1>${escapeHTML(data.display?.title ?? "未命名事件")}</h1>
      <div class="hero-meta">${typeChip(data.display?.type)}<span class="chip">${escapeHTML(formatTime(data.time))}</span><span class="chip">${escapeHTML(data.source_count ?? reps.length)} 个来源</span></div>
      <p class="lede">这里的标题是导航用 presentation label。史料记录、Claim、原始 evidence 和 Resolution 决策在下面保持分层，不会被合成为一段“权威叙事”。</p>
    </header>

    <div class="detail-grid">
      <div class="detail-main">
        <section class="panel"><div class="panel-heading"><h2>史料与证据</h2><span class="count">${escapeHTML(reps.length)} representations</span></div><div class="source-stack">${reps.map(eventRepresentation).join("")}</div></section>
        <section class="panel"><div class="panel-heading"><h2>Resolution</h2><span class="count">跨来源判断</span></div>${resolutionBlock(data.resolution_links ?? [], "event", data.canonical_event_id)}</section>
      </div>
      <aside class="detail-side">
        <section class="panel"><div class="panel-heading"><h2>人物 / 实体</h2><span class="count">participants</span></div><div class="entity-links">${participants.length ? participants.map((item) => linkedEntity(item, (item.source_roles ?? []).map((role) => role.role).filter(Boolean).join(" · ") || "participant")).join("") : `<p class="muted">没有 participant 映射。</p>`}</div></section>
        <section class="panel"><div class="panel-heading"><h2>地点</h2><span class="count">places</span></div><div class="entity-links">${places.length ? places.map((item) => linkedEntity(item, "place")).join("") : `<p class="muted">没有地点映射。</p>`}</div></section>
        <section class="panel"><div class="panel-heading"><h2>相关事件</h2><span class="count">related ≠ same</span></div><div class="related-list">${relatedCards || `<p class="muted">没有 related occurrence。</p>`}</div></section>
      </aside>
    </div>
  </section>`;
}

function entityRepresentation(rep) {
  const entity = rep.entity ?? {};
  const aliases = Array.isArray(entity.aliases) && entity.aliases.length
    ? `<div class="chip-row">${entity.aliases.map((alias) => `<span class="chip">${escapeHTML(alias)}</span>`).join("")}</div>`
    : "";
  return `<article class="source-card" data-source="${escapeHTML(rep.bundle)}">
    <header><div><div class="source-title">${escapeHTML(rep.source?.title ?? rep.bundle)}</div><div class="muted">Source representation</div></div><code>${escapeHTML(rep.bundle)}:${escapeHTML(rep.ref)}</code></header>
    ${aliases}
    ${claimsBlock(rep.claims ?? [])}
    ${detailsJSON("查看源 Entity 记录", entity)}
    ${detailsJSON("查看 Source 元数据", rep.source?.record ?? {})}
  </article>`;
}

function involvementChips(involvements = []) {
  const roles = new Set();
  let asPlace = false;
  for (const item of involvements) {
    for (const role of item.participant_roles ?? []) roles.add(role);
    if (item.as_place) asPlace = true;
  }
  const chips = [...roles].sort().map((role) => `<span class="role-chip">${escapeHTML(role)}</span>`);
  if (asPlace) chips.push(`<span class="role-chip">作为地点</span>`);
  return chips.join("");
}

export function renderEntity(data) {
  const reps = data?.representations ?? [];
  const events = data?.events ?? [];
  const claims = data?.claims ?? [];
  const trajectory = events.map((event) => `<a class="trajectory-card" href="${eventHref(event.canonical_event_id)}" data-test="trajectory-event">
    <strong>${escapeHTML(event.display?.title ?? "未命名事件")}</strong>
    <span class="muted">${escapeHTML(formatTime(event.time))}</span>
    <div class="trajectory-meta">${involvementChips(event.source_involvements ?? [])}</div>
  </a>`).join("");

  return `<section data-view="entity" data-canonical-id="${escapeHTML(data.canonical_entity_id)}">
    <div class="breadcrumbs"><a href="/timeline">时间线</a><span>›</span><span>实体</span></div>
    <header class="page-header">
      <p class="eyebrow">Canonical Entity</p>
      <h1>${escapeHTML(data.display?.name ?? "未命名实体")}</h1>
      <div class="hero-meta">${typeChip(data.display?.type)}<span class="chip">${escapeHTML(data.source_count ?? reps.length)} 个来源</span><span class="chip">${escapeHTML(data.representation_count ?? reps.length)} 条记录</span></div>
      <p class="lede">Canonical UUID 只负责跨来源导航。相同名称但身份不确定的地点保持不同页面，并通过 Resolution 明确显示“不确定”。</p>
    </header>

    <div class="detail-grid">
      <div class="detail-main">
        <section class="panel"><div class="panel-heading"><h2>事件轨迹</h2><span class="count">${escapeHTML(events.length)} canonical Events</span></div><div class="trajectory-list">${trajectory || `<p class="muted">暂时没有关联事件。</p>`}</div></section>
        <section class="panel"><div class="panel-heading"><h2>来源表示</h2><span class="count">${escapeHTML(reps.length)} representations</span></div><div class="source-stack">${reps.map(entityRepresentation).join("")}</div></section>
      </div>
      <aside class="detail-side">
        <section class="panel"><div class="panel-heading"><h2>Resolution</h2><span class="count">identity</span></div>${resolutionBlock(data.resolution_links ?? [], "entity", data.canonical_entity_id)}</section>
        <section class="panel"><div class="panel-heading"><h2>直接 Claims</h2><span class="count">${escapeHTML(claims.length)}</span></div>${claimsBlock(claims)}</section>
      </aside>
    </div>
  </section>`;
}

export function renderLoading(label = "历史数据") {
  return `<section class="state-card"><p class="eyebrow">Chronicle</p><h1>正在读取${escapeHTML(label)}…</h1><p class="muted">数据来自 C0-T10 read API。</p></section>`;
}

export function renderError(error) {
  const code = error?.code ?? "request_failed";
  const message = error?.message ?? String(error ?? "未知错误");
  return `<section class="state-card error-card" data-view="error"><p class="eyebrow">${escapeHTML(code)}</p><h1>无法读取这个历史页面</h1><p>${escapeHTML(message)}</p><p><a href="/timeline">返回时间线</a></p></section>`;
}

export function renderNotFound() {
  return `<section class="state-card error-card" data-view="not-found"><p class="eyebrow">404</p><h1>这个 Chronicle 页面不存在</h1><p><a href="/timeline">返回时间线</a></p></section>`;
}

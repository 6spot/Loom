import { escapeHTML, formatTime } from "./ui.mjs";

function searchHref(query) {
  return `/search?q=${encodeURIComponent(query ?? "")}`;
}

export function searchApiPath(search = "") {
  const incoming = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const outgoing = new URLSearchParams();
  const q = (incoming.get("q") ?? "").trim();
  outgoing.set("q", q);
  const kind = incoming.get("kind");
  if (kind) outgoing.set("kind", kind);
  const limit = incoming.get("limit");
  outgoing.set("limit", limit || "20");
  return `/v0/search?${outgoing.toString()}`;
}

function matchLabel(match) {
  return {
    exact: "完全匹配",
    prefix: "前缀匹配",
    substring: "包含匹配",
  }[match] ?? match ?? "匹配";
}

function matchedSurface(surface) {
  const source = surface.source_title
    ? `<span class="match-source">${escapeHTML(surface.source_title)}</span>`
    : `<span class="match-source">canonical 展示</span>`;
  return `<li>
    ${source}
    <span class="match-field">${escapeHTML(surface.field)}</span>
    <span class="match-kind">${escapeHTML(matchLabel(surface.match))}</span>
    <q>${escapeHTML(surface.value)}</q>
  </li>`;
}

function entityCard(item) {
  const uncertainty = item.identity_uncertain
    ? `<span class="decision uncertain">身份不确定</span>`
    : "";
  return `<article class="search-card entity-result" data-search-kind="entity" data-canonical-id="${escapeHTML(item.canonical_id)}">
    <div class="search-card-topline"><span class="chip type">Entity</span>${uncertainty}<span class="count">rank ${escapeHTML(item.match?.rank ?? "—")}</span></div>
    <h2><a href="${escapeHTML(item.navigation_path)}">${escapeHTML(item.display?.name ?? "未命名实体")}</a></h2>
    <div class="hero-meta"><span class="chip">${escapeHTML(item.display?.type ?? "entity")}</span><span class="chip">${escapeHTML(item.source_count ?? 0)} 个来源</span><span class="chip">${escapeHTML(item.representation_count ?? 0)} 条记录</span></div>
    <details class="search-match"><summary>为什么命中</summary><ul>${(item.match?.matched_surfaces ?? []).slice(0, 6).map(matchedSurface).join("")}</ul></details>
  </article>`;
}

function eventCard(item) {
  return `<article class="search-card event-result" data-search-kind="event" data-canonical-id="${escapeHTML(item.canonical_id)}">
    <div class="search-card-topline"><span class="chip type">Event</span><span class="count">rank ${escapeHTML(item.match?.rank ?? "—")}</span></div>
    <h2><a href="${escapeHTML(item.navigation_path)}">${escapeHTML(item.display?.title ?? "未命名事件")}</a></h2>
    <p class="search-time">${escapeHTML(formatTime(item.time))}</p>
    <div class="hero-meta"><span class="chip">${escapeHTML(item.display?.type ?? "event")}</span><span class="chip">${escapeHTML(item.source_count ?? 0)} 个来源</span><span class="chip">${escapeHTML(item.representation_count ?? 0)} 条记录</span></div>
    <details class="search-match"><summary>为什么命中</summary><ul>${(item.match?.matched_surfaces ?? []).slice(0, 6).map(matchedSurface).join("")}</ul></details>
  </article>`;
}

export function renderSearchEmpty(query = "") {
  return `<section data-view="search">
    <header class="page-header">
      <p class="eyebrow">Search</p>
      <h1>搜索历史世界</h1>
      <p class="lede">输入人物、地点或事件，例如「曹操」「赤壁」「江陵」。结果以 canonical Entity/Event 导航，来源命中理由保持可见。</p>
    </header>
    <form class="search-page-form" action="/search" method="get">
      <label for="search-page-q">搜索词</label>
      <div class="search-row"><input id="search-page-q" name="q" value="${escapeHTML(query)}" autocomplete="off" placeholder="曹操、赤壁之战、江陵…"><button class="primary-button" type="submit">搜索</button></div>
    </form>
    <section class="state-card empty-card"><h2>从一个名字或事件开始</h2><p class="muted">C0-T12 只做可解释的词面检索，不会用模型生成一个看似权威的历史答案。</p></section>
  </section>`;
}

export function renderSearch(data) {
  const items = data?.items ?? [];
  const query = data?.query?.q ?? "";
  const page = data?.page ?? { total: items.length, returned: items.length, has_more: false };
  const cards = items.map((item) => item.kind === "entity" ? entityCard(item) : eventCard(item)).join("");
  const more = page.has_more
    ? `<p class="muted">还有更多匹配；当前 v0 只展示前 ${escapeHTML(page.returned)} 条，可收窄查询词。</p>`
    : "";
  return `<section data-view="search">
    <header class="page-header">
      <p class="eyebrow">Search</p>
      <h1>“${escapeHTML(query)}” 的搜索结果</h1>
      <p class="lede">同一 canonical 对象只出现一次；展开“为什么命中”可以看到具体来源表示和匹配字段。</p>
    </header>
    <form class="search-page-form" action="/search" method="get">
      <label for="search-page-q">搜索词</label>
      <div class="search-row"><input id="search-page-q" name="q" value="${escapeHTML(query)}" autocomplete="off"><button class="primary-button" type="submit">搜索</button></div>
    </form>
    <div class="page-stats"><span>共 ${escapeHTML(page.total ?? items.length)} 个 canonical 结果</span><span>显示 ${escapeHTML(page.returned ?? items.length)} 个</span></div>
    ${items.length ? `<div class="search-results">${cards}</div>${more}` : `<section class="state-card empty-card"><h2>没有找到匹配结果</h2><p class="muted">这只表示当前 Chronicle 语料里没有词面命中，不代表历史上不存在相关人物或事件。</p><p><a href="${searchHref("")}">换一个搜索词</a></p></section>`}
  </section>`;
}

import { Link, useSearchParams } from "react-router-dom";
import { useSearch } from "../../lib/queries";
import { formatTime } from "../../lib/routes";
import { ErrorState, LoadingState } from "../../components/shared";
import type { SearchItem, SearchSurface } from "../../lib/types";

const MATCH_LABEL: Record<string, string> = {
  exact: "完全匹配",
  prefix: "前缀匹配",
  substring: "包含匹配",
};

function MatchedSurface({ surface }: { surface: SearchSurface }) {
  return (
    <li>
      {surface.source_title ? (
        <span className="match-source">{surface.source_title}</span>
      ) : (
        <span className="match-source">canonical 展示</span>
      )}{" "}
      <span className="match-field">{surface.field}</span>{" "}
      <span className="match-kind">{MATCH_LABEL[surface.match ?? ""] ?? surface.match ?? "匹配"}</span>{" "}
      <q>{surface.value}</q>
    </li>
  );
}

function EntityCard({ item }: { item: SearchItem }) {
  return (
    <article className="search-card entity-result" data-search-kind="entity" data-canonical-id={item.canonical_id}>
      <div className="search-card-topline">
        <span className="chip type">Entity</span>
        {item.identity_uncertain ? <span className="decision uncertain">身份不确定</span> : null}
        <span className="count">rank {item.match?.rank ?? "—"}</span>
      </div>
      <h2>
        <Link to={item.navigation_path}>{item.display?.name ?? "未命名实体"}</Link>
      </h2>
      <div className="hero-meta">
        <span className="chip">{item.display?.type ?? "entity"}</span>
        <span className="chip">{item.source_count ?? 0} 个来源</span>
        <span className="chip">{item.representation_count ?? 0} 条记录</span>
      </div>
      <details className="search-match">
        <summary>为什么命中</summary>
        <ul>{(item.match?.matched_surfaces ?? []).slice(0, 6).map((surface, index) => (
          <MatchedSurface key={index} surface={surface} />
        ))}</ul>
      </details>
    </article>
  );
}

function EventCard({ item }: { item: SearchItem }) {
  return (
    <article className="search-card event-result" data-search-kind="event" data-canonical-id={item.canonical_id}>
      <div className="search-card-topline">
        <span className="chip type">Event</span>
        <span className="count">rank {item.match?.rank ?? "—"}</span>
      </div>
      <h2>
        <Link to={item.navigation_path}>{item.display?.title ?? "未命名事件"}</Link>
      </h2>
      <p className="search-time">{formatTime(item.time ?? {})}</p>
      <div className="hero-meta">
        <span className="chip">{item.display?.type ?? "event"}</span>
        <span className="chip">{item.source_count ?? 0} 个来源</span>
        <span className="chip">{item.representation_count ?? 0} 条记录</span>
      </div>
      <details className="search-match">
        <summary>为什么命中</summary>
        <ul>{(item.match?.matched_surfaces ?? []).slice(0, 6).map((surface, index) => (
          <MatchedSurface key={index} surface={surface} />
        ))}</ul>
      </details>
    </article>
  );
}

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim();
  const search = useSearch(`?${searchParams.toString()}`);

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = new URLSearchParams(searchParams);
    next.set("q", String(form.get("q") ?? "").trim());
    setSearchParams(next);
  };

  const form = (
    <form className="search-page-form" action="/search" method="get" onSubmit={submit}>
      <label htmlFor="search-page-q">搜索词</label>
      <div className="search-row">
        <input id="search-page-q" name="q" defaultValue={q} autoComplete="off" placeholder="曹操、赤壁之战、江陵…" />
        <button className="primary-button" type="submit">
          搜索
        </button>
      </div>
    </form>
  );

  if (!q) {
    return (
      <section data-view="search">
        <header className="page-header">
          <p className="eyebrow">Search</p>
          <h1>搜索历史世界</h1>
          <p className="lede">输入人物、地点或事件，例如「曹操」「赤壁」「江陵」。结果以 canonical Entity/Event 导航，来源命中理由保持可见。</p>
        </header>
        {form}
        <section className="state-card empty-card">
          <h2>从一个名字或事件开始</h2>
          <p className="muted">Chronicle 只做可解释的词面检索，不会用模型生成一个看似权威的历史答案。</p>
        </section>
      </section>
    );
  }

  if (search.isPending) return <LoadingState label="搜索结果" />;
  if (search.isError) return <ErrorState code={search.error.code} message={search.error.message} />;

  const data = search.data;
  const items = data.items ?? [];
  const page = data.page ?? { total: items.length, returned: items.length, has_more: false };

  return (
    <section data-view="search">
      <header className="page-header">
        <p className="eyebrow">Search</p>
        <h1>“{data.query?.q ?? q}” 的搜索结果</h1>
        <p className="lede">同一 canonical 对象只出现一次；展开“为什么命中”可以看到具体来源表示和匹配字段。</p>
      </header>
      {form}
      <div className="page-stats">
        <span>共 {page.total ?? items.length} 个 canonical 结果</span>
        <span>显示 {page.returned ?? items.length} 个</span>
      </div>
      {items.length ? (
        <>
          <div className="search-results">
            {items.map((item) => (item.kind === "entity" ? <EntityCard key={item.canonical_id} item={item} /> : <EventCard key={item.canonical_id} item={item} />))}
          </div>
          {page.has_more ? (
            <p className="muted">还有更多匹配；当前只展示前 {page.returned} 条，可收窄查询词。</p>
          ) : null}
        </>
      ) : (
        <section className="state-card empty-card">
          <h2>没有找到匹配结果</h2>
          <p className="muted">这只表示当前 Chronicle 语料里没有词面命中，不代表历史上不存在相关人物或事件。</p>
        </section>
      )}
    </section>
  );
}

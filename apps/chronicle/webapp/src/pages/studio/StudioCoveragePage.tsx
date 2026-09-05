import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { getStudioCoverage } from "../../lib/coverage-api";
import { formatShortHash, listDocuments, StudioApiError } from "../../lib/studio-api";
import { useStudioAuth } from "../../lib/studio-auth";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

export default function StudioCoveragePage() {
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const coverage = useQuery({
    queryKey: ["studio", "coverage"],
    queryFn: () => getStudioCoverage(authHeader),
  });
  const documents = useQuery({
    queryKey: ["studio", "documents"],
    queryFn: () => listDocuments(authHeader),
  });

  const sparseYears = useMemo(
    () => coverage.data?.time.years.filter((item) => item.density !== "represented") ?? [],
    [coverage.data],
  );
  const sources = useMemo(
    () => coverage.data?.sources.slice().sort((a, b) =>
      a.canonical_event_count - b.canonical_event_count ||
      a.canonical_entity_count - b.canonical_entity_count ||
      (a.source_title ?? a.bundle).localeCompare(b.source_title ?? b.bundle),
    ) ?? [],
    [coverage.data],
  );
  const maxEvents = Math.max(1, ...(coverage.data?.time.years.map((item) => item.event_count) ?? [1]));

  if (coverage.isLoading) {
    return <p className="studio-muted">正在重算 Coverage…</p>;
  }
  if (coverage.error) {
    return <p className="studio-error">Coverage 读取失败：{errorText(coverage.error)}</p>;
  }
  if (!coverage.data) return null;

  const data = coverage.data;
  const presentationTargetCount = data.presentations.entity_targets + data.presentations.event_targets;
  const presentedTargetCount = data.presentations.published_entity_targets + data.presentations.published_event_targets;

  return (
    <div className="studio-stack" data-view="studio-coverage">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">C1 · derived corpus measurement</p>
          <h1>Coverage</h1>
          <p className="studio-muted">
            只测量 Chronicle 当前已发布语料的表示密度；不是历史完整度，也不会写回 Entity / Event / Claim / Resolution。
          </p>
        </div>
        <Button variant="outline" onClick={() => void Promise.all([coverage.refetch(), documents.refetch()])} disabled={coverage.isFetching}>
          {coverage.isFetching ? "重算中…" : "重新计算"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>解释边界</CardTitle>
          <CardDescription>Public Historical Moment 必须继承同一条 no-data 语义。</CardDescription>
        </CardHeader>
        <CardContent>
          <p>{data.authority.absence_semantics}</p>
          <p className="studio-muted">{data.authority.density_semantics}</p>
          <p className="studio-muted">{data.authority.domain_semantics}</p>
          <div className="studio-row-title">
            <Badge>{data.authority.kind}</Badge>
            <Badge>historical_truth=false</Badge>
            <Badge>mutates_history=false</Badge>
            <span className="studio-mono">catalog {formatShortHash(data.catalog.latest_catalog_sha256)}</span>
          </div>
        </CardContent>
      </Card>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>Corpus snapshot</CardTitle>
            <CardDescription>当前 canonical catalog 与上传 Document 的可见密度。</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="studio-facts">
              <div><dt>Published sources</dt><dd>{data.catalog.published_source_bundle_count}</dd></div>
              <div><dt>Documents</dt><dd>{documents.data?.length ?? "…"}</dd></div>
              <div><dt>Canonical Entities</dt><dd>{data.entities.canonical_count}</dd></div>
              <div><dt>Canonical Events</dt><dd>{data.events.canonical_count}</dd></div>
              <div><dt>Claims in published sources</dt><dd>{data.claims.published_source_claim_count}</dd></div>
              <div><dt>Open resolution reviews</dt><dd>{data.review_debt.open_resolution}</dd></div>
              <div><dt>Published presentations</dt><dd>{presentedTargetCount} / {presentationTargetCount}</dd></div>
              <div><dt>Unknown-time Events</dt><dd>{data.time.unknown_time_event_count}</dd></div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Actionable gaps</CardTitle>
            <CardDescription>用于决定下一批来源，不生成自动“完整度”结论。</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="studio-links">
              <li>{sparseYears.length} 个年份在当前已知时间跨度内被标为 sparse / unrepresented。</li>
              <li>{data.presentations.entity_targets_without_published_presentation} 个 Entity 与 {data.presentations.event_targets_without_published_presentation} 个 Event 当前没有 published Reader Presentation。</li>
              <li>{data.review_debt.open_resolution} 个 resolution review 仍未解决。</li>
              <li>{sources[0] ? `当前事件贡献最少的 published source：${sources[0].source_title ?? sources[0].bundle}（${sources[0].canonical_event_count} Events）` : "当前没有 published source contribution。"}</li>
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Time density</CardTitle>
          <CardDescription>
            observed normalized year：{data.time.known_year_span.start_year ?? "?"}–{data.time.known_year_span.end_year ?? "?"}。0 只表示当前 corpus 未表示。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="studio-table" aria-label="Coverage by year">
            {data.time.years.map((item) => (
              <div className="studio-table-row" key={item.year}>
                <div>
                  <div className="studio-row-title"><strong>{item.year}</strong><Badge>{item.density}</Badge></div>
                  <div className="studio-muted">{item.event_count} Events · {item.source_count} Sources</div>
                </div>
                <div className="studio-row-actions">
                  <progress max={maxEvents} value={item.event_count} aria-label={`${item.year} event density`} />
                  <span>{item.event_types.map((type) => `${type.value} ${type.count}`).join(" · ") || "—"}</span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>Source contribution</CardTitle>
            <CardDescription>按 latest canonical catalog 中的 representation 与 published-source Claims 计数。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="studio-table">
              {sources.map((source) => (
                <div className="studio-table-row" key={source.bundle}>
                  <div><strong>{source.source_title ?? source.bundle}</strong><div className="studio-muted">{source.bundle}</div></div>
                  <div className="studio-row-actions">{source.canonical_entity_count} Entities · {source.canonical_event_count} Events · {source.claim_count} Claims</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Event / Claim domains</CardTitle>
            <CardDescription>{data.domains.basis} 与 persisted Claim predicate 的 corpus-relative 分布。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="studio-grid studio-grid-compact">
              <div>
                <h3>Event types</h3>
                <ul>{data.domains.event_types.map((item) => <li key={item.value}>{item.value}: {item.count}</li>)}</ul>
              </div>
              <div>
                <h3>Claim predicates</h3>
                <ul>{data.domains.claim_predicates.map((item) => <li key={item.value}>{item.value}: {item.count}</li>)}</ul>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

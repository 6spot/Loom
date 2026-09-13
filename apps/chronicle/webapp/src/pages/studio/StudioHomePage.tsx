import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useStudioAuth } from "../../lib/studio-auth";
import { listDocuments, listJobs, listReviewPage } from "../../lib/studio-api";
import { studioStatusLabel } from "../../lib/studio-i18n";
import { formatStudioTime, jobNextAction, jobTitle, reviewKind } from "../../lib/studio-workspace";

export default function StudioHomePage() {
  const auth = useStudioAuth();
  const header = auth.authHeader();
  const jobs = useQuery({ queryKey: ["studio", "jobs", "all", 0], queryFn: () => listJobs(header), refetchInterval: 8000 });
  const reviews = useQuery({ queryKey: ["studio", "reviews", "overview"], queryFn: () => listReviewPage(header, { reviewScope: "all", status: "open", limit: 5 }), refetchInterval: 8000 });
  const documents = useQuery({ queryKey: ["studio", "documents"], queryFn: () => listDocuments(header) });
  const status = useQuery({ queryKey: ["studio", "service-status"], queryFn: () => auth.authedFetch("/api/v1/studio/status") });
  const active = jobs.data?.filter((job) => job.status === "running").length;
  const failed = jobs.data?.filter((job) => job.status === "failed").length;
  return <div className="studio-stack" data-view="studio-home">
    <div className="studio-page-heading"><div><p className="studio-eyebrow">Studio 总览</p><h1>内容工作台</h1><p className="studio-muted">整理史料，核对分歧，让历史连贯地呈现。</p></div><Link className="studio-link-button studio-link-primary" to="/studio/sources?upload=1">＋ 上传资料</Link></div>
    <div className="studio-overview-metrics">
      <Link to="/studio/review?review_scope=all"><span>等待内容核对</span><strong>{reviews.data?.open_count ?? "—"}</strong><small>查看并继续审核 →</small></Link>
      <Link to="/studio/imports?status=running"><span>正在生产</span><strong>{active ?? "—"}</strong><small>最近 100 项任务</small></Link>
      <Link to="/studio/imports?status=failed" data-tone="attention"><span>需要处理</span><strong>{failed ?? "—"}</strong><small>最近 100 项任务中的失败项</small></Link>
      <Link to="/studio/sources"><span>已收录史料</span><strong>{documents.data?.length ?? "—"}</strong><small>查看资料与版本 →</small></Link>
    </div>
    <div className="studio-overview-grid">
      <section className="studio-panel"><div className="studio-section-heading"><div><p className="studio-eyebrow">优先处理</p><h2>待核对内容</h2></div><Link to="/studio/review?review_scope=all">全部审核 →</Link></div>
        {reviews.error ? <p className="studio-error" role="alert">审核队列暂时无法读取。</p> : reviews.isPending ? <p className="studio-muted">正在读取…</p> : reviews.data?.items.length === 0 ? <div className="studio-empty"><strong>当前没有待审核内容</strong><p>处理中的任务出现分歧或需要确认时，会汇总到这里。</p></div> : null}
        {reviews.data?.items.map((review) => <Link className="studio-inbox-row" key={review.review_id} to={`/studio/review/${review.review_id}?review_scope=all`}><span className="studio-inbox-dot" /><div><strong>{review.document.title}</strong><p>{reviewKind(review.scope, review.narrative_kind)}{review.issue_count != null ? ` · ${review.issue_count} 条意见` : ""}</p></div><span aria-hidden="true">→</span></Link>)}
      </section>
      <section className="studio-panel studio-production-guide"><p className="studio-eyebrow">从资料到历史</p><h2>继续完善历史叙事</h2><ol><li><span>01</span><div><strong>整理完整史料</strong><p>整章翻译，同时提取人物与事件。</p></div></li><li><span>02</span><div><strong>对比与核对</strong><p>查看多模型意见及跨来源依据。</p></div></li><li><span>03</span><div><strong>生成连续历史</strong><p>审核正文、人物状态与精选入口。</p></div></li></ol><Link className="studio-link-button" to="/studio/imports?create=history">选择来源并生成历史 →</Link></section>
    </div>
    <section className="studio-panel"><div className="studio-section-heading"><h2>最近生产任务</h2><Link to="/studio/imports">全部任务 →</Link></div>{jobs.error ? <p role="alert" className="studio-error">任务读取失败，请稍后刷新。</p> : null}
      {jobs.data?.slice(0, 6).map((job) => <Link key={job.job_id} className="studio-table-row" to={`/studio/imports/${job.job_id}`}><div><strong>{jobTitle(job)}</strong><p className="studio-muted">{jobNextAction(job)}</p></div><span className="studio-status" data-status={job.status}>{studioStatusLabel(job.status)}</span><time className="studio-muted">{formatStudioTime(job.updated_at)}</time></Link>)}
      {jobs.data?.length === 0 ? <p className="studio-muted">还没有生产任务，先上传一份史料开始。</p> : null}
    </section>
    <p className="studio-system-status"><span data-status={status.data?.upstream.reachable ? "completed" : "failed"} />{status.isPending ? "正在连接内容服务" : status.data?.upstream.reachable ? "内容服务已连接" : "内容服务暂不可达，请检查连接"}</p>
  </div>;
}

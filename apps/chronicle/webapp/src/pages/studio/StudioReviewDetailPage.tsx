import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import {
  getReview,
  mutateJob,
  StudioApiError,
  submitReviewDecision,
} from "../../lib/studio-api";
import type {
  ReviewDecision,
  ReviewGroupDetail,
  ReviewGroupDecisionInput,
  ReviewRecordContext,
} from "../../lib/studio-api";
import {
  comparisonRows,
  decisionHelp,
  decisionLabel,
  formatLocator,
  formatReviewTime,
  roleLabel,
  signalLabel,
  statusLabel,
  typeLabel,
} from "../../lib/review-display";
import type { HumanReviewContext } from "../../lib/review-display";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

type GroupOverrideDraft = {
  enabled: boolean;
  decision: ReviewDecision | "";
  rationale: string;
  confidence: string;
};

function pretty(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function EvidenceList({ context }: { context: HumanReviewContext }) {
  const evidence = context.display?.evidence ?? [];
  return (
    <div className="studio-stack">
      <div>
        <strong>来源逐字证据</strong>
        <p className="studio-muted">仅展示当前暂存数据包中直接引用该记录的事实声明逐字证据；这些文字是人工判断的主要依据。</p>
      </div>
      {evidence.length ? (
        evidence.map((item) => (
          <div className="studio-run" key={`${item.claim_ref}:${item.text}`}>
            <p style={{ margin: 0, fontSize: "0.95rem", lineHeight: 1.7 }}>「{item.text}」</p>
            <p className="studio-muted" style={{ marginBottom: 0 }}>
              {formatLocator(item.locator)}
            </p>
          </div>
        ))
      ) : (
        <p className="studio-error-box">
          当前记录没有直接关联的事实声明逐字证据。不要仅凭名称、标题或内部 ID 合并；证据不足时应选择“证据不足，暂不确定”。
        </p>
      )}
    </div>
  );
}

function RecordCard({ label, context }: { label: string; context: ReviewRecordContext }) {
  const human = context as HumanReviewContext;
  const record = context.record ?? {};
  const display = human.display ?? {};
  const title = display.name ?? record.name ?? record.title ?? context.ref;
  const participants = display.participants ?? [];
  const places = display.places ?? [];
  const aliases = (display.aliases ?? []).map(String).filter(Boolean);
  const mentions = display.mentions ?? [];

  return (
    <Card>
      <CardHeader>
        <p className="studio-eyebrow">{label}</p>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          来源：{context.source_title ?? "未知来源"}
        </CardDescription>
      </CardHeader>
      <CardContent className="studio-stack">
        <dl className="studio-definition-list">
          <div><dt>记录类型</dt><dd>{typeLabel(display.type ?? record.type)}</dd></div>
          {display.time ? <div><dt>时间</dt><dd>{formatReviewTime(display.time)}</dd></div> : null}
          {aliases.length ? <div><dt>别名</dt><dd>{aliases.join("、")}</dd></div> : null}
          {mentions.length ? <div><dt>原文称呼</dt><dd>{mentions.join("、")}</dd></div> : null}
          {participants.length ? (
            <div>
              <dt>参与者</dt>
              <dd>{participants.map((item) => `${item.name}（${roleLabel(item.role)}）`).join("、")}</dd>
            </div>
          ) : null}
          {places.length ? <div><dt>地点</dt><dd>{places.map((item) => item.name).join("、")}</dd></div> : null}
          {display.summary ? (
            <div>
              <dt>记录摘要</dt>
              <dd>{display.summary}<span className="studio-muted">（摘要不是逐字证据）</span></dd>
            </div>
          ) : null}
        </dl>

        <EvidenceList context={human} />

        <details className="studio-details">
          <summary>技术详情 / 审计字段</summary>
          <p className="studio-muted">内部枚举、临时 ID 和原始 JSON 仅用于审计，不应作为人工合并依据。</p>
          <pre className="studio-code">{pretty({
            bundle: context.bundle,
            ref: context.ref,
            source_ref: context.source_ref,
            record,
          })}</pre>
        </details>
      </CardContent>
    </Card>
  );
}

export function CanonicalIdentityConflictNotice({
  error, reviewGroups = [],
}: { error: StudioApiError; reviewGroups?: ReviewGroupDetail[] }) {
  const details = error.details;
  const groups = details?.review_groups ?? [];
  const incoming = groups.length
    ? groups.map((group) => ({
      id: group.review_group_id,
      number: reviewGroups.findIndex((item) => item.review_group_id === group.review_group_id) + 1,
      contexts: group.right_contexts,
    }))
    : [{ id: "incoming", number: 0, contexts: details?.incoming_contexts ?? [] }];

  return (
    <section className="studio-error-box studio-stack" role="alert" aria-label="实体身份冲突">
      <strong>该判断无法提交</strong>
      <p>
        它会把当前来源实体同时连接到两个已经发布的实体。Chronicle 不允许在普通导入审核中合并两个既有实体。
        本次判断未保存，审核项仍待处理，之前的审核记录保持不变。
      </p>
      {details?.canonical_entities?.length ? (
        <div>
          <strong>涉及的已发布实体</strong>
          <ul className="studio-links">
            {details.canonical_entities.map((entity) => {
              const sources = [...new Set(entity.contexts.map((context) => context.source_title).filter(Boolean))];
              return (
                <li key={entity.canonical_id}>
                  {entity.names.join("、") || "未命名实体"}
                  {sources.length ? `（来源：${sources.join("、")}）` : ""}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {incoming.filter((group) => group.contexts.length).map((group) => {
        const names = [...new Set(group.contexts.map((context) => (
          (context as HumanReviewContext).display?.name ?? context.record?.name
        )).filter(Boolean))];
        return (
          <div className="studio-stack" key={group.id}>
            <strong>需调整的来源候选组{group.number > 0 ? ` ${group.number}` : ""}：{names.join("、") || "未命名记录"}</strong>
            {group.contexts.map((context) => (
              <div key={`${context.bundle}:${context.ref}`}>
                <p className="studio-muted">来源：{context.source_title ?? "未知来源"}</p>
                <EvidenceList context={context as HumanReviewContext} />
              </div>
            ))}
          </div>
        );
      })}
      <p>
        请选择其中一个已发布实体作为“同一实体”，其他候选请选择“不是同一实体”或“证据不足，暂不确定”。
        如果批次中只有部分候选组冲突，可点击“存在例外，展开逐组判断”，修改这些组后重新提交。
      </p>
      <details className="studio-details">
        <summary>冲突技术详情 / 审计字段</summary>
        <pre className="studio-code">{pretty(details ?? { code: error.code, message: error.message })}</pre>
      </details>
    </section>
  );
}

export default function StudioReviewDetailPage() {
  const { reviewId = "" } = useParams();
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const review = useQuery({
    queryKey: ["studio", "review", reviewId],
    queryFn: () => getReview(authHeader, reviewId),
    enabled: Boolean(reviewId),
  });
  const item = review.data;
  const allowed = item?.allowed_decisions ?? [];
  const [decision, setDecision] = useState<ReviewDecision | "">("");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState("0.5");
  const [showExceptions, setShowExceptions] = useState(false);
  const [groupOverrides, setGroupOverrides] = useState<Record<string, GroupOverrideDraft>>({});

  useEffect(() => {
    if (!decision && allowed.length) setDecision(allowed[0]);
  }, [allowed, decision]);

  useEffect(() => {
    setShowExceptions(false);
    setGroupOverrides({});
  }, [reviewId]);

  const setGroupOverride = (groupId: string, patch: Partial<GroupOverrideDraft>) => {
    setGroupOverrides((current) => {
      const existing = current[groupId] ?? {
        enabled: false,
        decision: (decision || allowed[0] || "") as ReviewDecision | "",
        rationale: "",
        confidence: confidence || "0.5",
      };
      return { ...current, [groupId]: { ...existing, ...patch } };
    });
  };

  const canSubmit = useMemo(() => {
    const parsed = Number(confidence);
    const overridesValid = Object.values(groupOverrides).every((draft) => {
      if (!draft.enabled) return true;
      const groupConfidence = Number(draft.confidence);
      return Boolean(
        draft.decision &&
        allowed.includes(draft.decision as ReviewDecision) &&
        draft.rationale.trim() &&
        Number.isFinite(groupConfidence) &&
        groupConfidence >= 0 &&
        groupConfidence <= 1,
      );
    });
    return Boolean(
      item?.status === "open" &&
      decision &&
      allowed.includes(decision as ReviewDecision) &&
      rationale.trim() &&
      Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 &&
      overridesValid,
    );
  }, [allowed, confidence, decision, groupOverrides, item?.status, rationale]);

  const decide = useMutation({
    mutationFn: async () => {
      if (!item || !decision) throw new Error("缺少审核判断");
      if (!window.confirm(`确认提交“${decisionLabel(decision)}”？提交后该审核项将作为审计历史保留，不能静默改写。`)) {
        throw new Error("已取消提交");
      }
      const reviewGroups = item.review_groups ?? [];
      const groupDecisions: ReviewGroupDecisionInput[] = reviewGroups.flatMap((group) => {
        const draft = groupOverrides[group.review_group_id];
        if (!draft?.enabled || !draft.decision) return [];
        return [{
          review_group_id: group.review_group_id,
          decision: draft.decision as ReviewDecision,
          rationale: draft.rationale.trim(),
          confidence: Number(draft.confidence),
        }];
      });
      return submitReviewDecision(
        authHeader,
        item.review_id,
        decision,
        rationale.trim(),
        Number(confidence),
        groupDecisions,
      );
    },
    onSuccess: async (updated) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["studio", "reviews"] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "review", reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "job", updated.job_id] }),
      ]);
    },
  });

  const resume = useMutation({
    mutationFn: async () => {
      if (!item) throw new Error("缺少导入作业");
      if (!window.confirm("所有消歧审核已完成。确认通过控制平面恢复该导入作业？")) {
        throw new Error("已取消恢复");
      }
      return mutateJob(authHeader, item.job_id, "resume");
    },
    onSuccess: async (job) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
      navigate(`/studio/imports/${encodeURIComponent(job.job_id)}`);
    },
  });

  if (review.isLoading) return <p className="studio-muted">正在读取审核项…</p>;
  if (review.error) return <p className="studio-error">{errorText(review.error)}</p>;
  if (!item) return <p className="studio-muted">审核项不存在。</p>;

  const leftContexts = (item.left_contexts?.length ? item.left_contexts : [item.left_context]) as HumanReviewContext[];
  const rightContexts = (item.right_contexts?.length ? item.right_contexts : [item.right_context]) as HumanReviewContext[];
  const left = leftContexts[0];
  const right = rightContexts[0];
  const comparisons = comparisonRows(item.link_kind, left, right);
  const memberCount = item.member_count ?? 1;
  const reviewGroups = item.review_groups ?? [];
  const groupCount = item.group_count ?? (reviewGroups.length || 1);

  return (
    <div className="studio-stack" data-view="studio-review-detail">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">人工消歧</p>
          <h1>{item.link_kind === "entity" ? "实体是否同一身份" : "事件是否同一发生"}</h1>
          <p className="studio-muted">
            审核批次 {item.review_subject_id ?? item.candidate_id} · {groupCount} 个来源候选组 / {memberCount} 个底层候选
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>{statusLabel(item.status)}</Badge>
          <Badge>{statusLabel(item.job_status)}</Badge>
          <Link className="studio-link-button" to="/studio/review">返回审核队列</Link>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>审核来源</CardTitle>
          <CardDescription>该审核项绑定到一个不可变文献修订和一个持久化导入作业。</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="studio-definition-list">
            <div><dt>文档</dt><dd>{item.document.title} · 第 {item.document.revision_no} 版</dd></div>
            <div><dt>文件</dt><dd>{item.document.filename}</dd></div>
            <div><dt>源文件哈希</dt><dd className="studio-mono">{item.document.source_sha256}</dd></div>
            <div><dt>导入作业</dt><dd><Link to={`/studio/imports/${encodeURIComponent(item.job_id)}`}>{item.job_id}</Link></dd></div>
            <div><dt>该作业待处理消歧</dt><dd>{item.job_open_resolution_reviews}</dd></div>
          </dl>
          <div className="studio-row-actions">
            <Link className="studio-link-button" to={`/studio/imports/${encodeURIComponent(item.job_id)}`}>查看导入作业</Link>
            <Link className="studio-link-button" to="/studio/sources">查看来源</Link>
          </div>
        </CardContent>
      </Card>

      {memberCount > 1 || groupCount > 1 ? (
        <Card>
          <CardHeader>
            <CardTitle>重复问题已整理为审核批次</CardTitle>
            <CardDescription>
              该批次包含 {groupCount} 个来源候选组 / {memberCount} 个底层候选。批次只是把指向同一个已发布身份或事件的问题集中展示，绝不表示这些来源候选组彼此已经被认定为同一实体或同一次事件。
            </CardDescription>
          </CardHeader>
          <CardContent className="studio-stack">
            <p className="studio-safe-note">
              默认情况下你可以对整个批次给出一个判断；如果其中某组证据不同，使用“存在例外，展开逐组判断”，只覆盖那个例外组。所有候选 ID、来源引用和证据都会继续保留在审计记录中。
            </p>
            {item.status === "open" && groupCount > 1 ? (
              <Button type="button" variant="outline" onClick={() => setShowExceptions((value) => !value)}>
                {showExceptions ? "收起逐组判断" : "存在例外，展开逐组判断"}
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>关键对比</CardTitle>
          <CardDescription>这里只做字段对照和重合提示，不自动产生身份或事件合并结论。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="studio-table">
            {comparisons.map((row) => (
              <div className="studio-table-row" key={row.label}>
                <strong>{row.label}</strong>
                <span>{row.left}</span>
                <span>{row.right}</span>
                <Badge>{row.result}</Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="studio-grid studio-grid-wide">
        <div className="studio-stack">
          {leftContexts.map((context, index) => (
            <RecordCard key={`${context.bundle}:${context.ref}`} label={leftContexts.length > 1 ? `已发布侧记录 ${index + 1}` : "已发布侧记录"} context={context} />
          ))}
        </div>
        <div className="studio-stack">
          {rightContexts.map((context, index) => (
            <RecordCard key={`${context.bundle}:${context.ref}`} label={rightContexts.length > 1 ? `本次来源记录 ${index + 1}` : "本次来源记录"} context={context} />
          ))}
        </div>
      </div>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>系统初始建议</CardTitle>
            <CardDescription>只作为辅助线索，不是历史身份权威；同名、同年或参与者重合都不能单独证明应当合并。</CardDescription>
          </CardHeader>
          <CardContent className="studio-stack">
            <dl className="studio-definition-list">
              <div><dt>建议</dt><dd><Badge>{decisionLabel(item.suggestion.decision)}</Badge></dd></div>
              <div><dt>建议置信度</dt><dd>{item.suggestion.confidence == null ? "—" : item.suggestion.confidence}</dd></div>
            </dl>
            {item.suggestion.signals.length ? (
              <div>
                <strong>系统发现的匹配信号</strong>
                <ul className="studio-links">
                  {item.suggestion.signals.map((signal, index) => <li key={index}>{signalLabel(signal)}</li>)}
                </ul>
              </div>
            ) : <p className="studio-muted">没有额外匹配信号。</p>}
            <details className="studio-details">
              <summary>查看原始系统建议 / 技术字段</summary>
              <pre className="studio-code">{pretty(item.suggestion)}</pre>
            </details>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>你的人工判断</CardTitle>
            <CardDescription>只根据上方来源证据作决定；“证据不足，暂不确定”不会触发合并。默认判断应用到未设置例外的候选组，逐组例外只覆盖对应组。</CardDescription>
          </CardHeader>
          <CardContent>
            {item.decision ? (
              <dl className="studio-definition-list">
                <div><dt>判断</dt><dd><Badge>{decisionLabel(item.decision.decision)}</Badge></dd></div>
                <div><dt>置信度</dt><dd>{item.decision.confidence}</dd></div>
                <div><dt>判断依据</dt><dd>{item.decision.rationale}</dd></div>
                {item.decision.group_decisions?.length ? (
                  <div>
                    <dt>逐组例外</dt>
                    <dd>{item.decision.group_decisions.map((group) => `${group.review_group_id}：${decisionLabel(group.decision)}（${group.rationale}）`).join("；")}</dd>
                  </div>
                ) : null}
                <div><dt>处理时间</dt><dd>{item.resolved_at ?? "—"}</dd></div>
              </dl>
            ) : (
              <form
                className="studio-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (canSubmit) decide.mutate();
                }}
              >
                <div>
                  <label className="studio-label" htmlFor="review-decision">你的判断</label>
                  <select
                    id="review-decision"
                    className="studio-select"
                    value={decision}
                    onChange={(event) => setDecision(event.target.value as ReviewDecision)}
                  >
                    {allowed.map((value) => <option key={value} value={value}>{decisionLabel(value)}</option>)}
                  </select>
                  {decision ? <p className="studio-muted">{decisionHelp(decision as ReviewDecision)}</p> : null}
                </div>
                <div>
                  <label className="studio-label" htmlFor="review-rationale">判断依据</label>
                  <textarea
                    id="review-rationale"
                    className="studio-textarea"
                    value={rationale}
                    onChange={(event) => setRationale(event.target.value)}
                    rows={5}
                    placeholder="写明你依据了哪些原文证据，以及为什么应合并、保持不同、判为相关但不同，或继续保持不确定。"
                  />
                </div>
                <div>
                  <label className="studio-label" htmlFor="review-confidence">判断置信度（0–1）</label>
                  <Input
                    id="review-confidence"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={confidence}
                    onChange={(event) => setConfidence(event.target.value)}
                  />
                </div>

                {showExceptions && reviewGroups.length > 1 ? (
                  <div className="studio-stack">
                    <div>
                      <strong>逐组例外判断</strong>
                      <p className="studio-muted">只有你明确启用的候选组才覆盖上面的默认判断。未启用的组继续使用默认判断；这里的分组不是身份结论。</p>
                    </div>
                    {reviewGroups.map((group, index) => {
                      const draft = groupOverrides[group.review_group_id] ?? {
                        enabled: false,
                        decision: (decision || allowed[0] || "") as ReviewDecision | "",
                        rationale: "",
                        confidence: confidence || "0.5",
                      };
                      const names = group.right_contexts
                        .map((context) => {
                          const human = context as HumanReviewContext;
                          return human.display?.name ?? context.record?.name ?? context.record?.title ?? context.ref;
                        })
                        .filter(Boolean);
                      return (
                        <Card key={group.review_group_id}>
                          <CardHeader>
                            <CardTitle>候选组 {index + 1}：{names.join("、") || "未命名记录"}</CardTitle>
                            <CardDescription>{group.member_count} 个底层候选 · 组 ID {group.review_group_id}</CardDescription>
                          </CardHeader>
                          <CardContent className="studio-stack">
                            {group.right_contexts.map((context) => (
                              <EvidenceList key={`${group.review_group_id}:${context.bundle}:${context.ref}`} context={context as HumanReviewContext} />
                            ))}
                            <Button
                              type="button"
                              variant={draft.enabled ? "default" : "outline"}
                              onClick={() => setGroupOverride(group.review_group_id, { enabled: !draft.enabled })}
                            >
                              {draft.enabled ? "取消此组例外，恢复默认判断" : "此组使用不同判断"}
                            </Button>
                            {draft.enabled ? (
                              <div className="studio-form">
                                <div>
                                  <label className="studio-label" htmlFor={`group-decision-${group.review_group_id}`}>此组判断</label>
                                  <select
                                    id={`group-decision-${group.review_group_id}`}
                                    className="studio-select"
                                    value={draft.decision}
                                    onChange={(event) => setGroupOverride(group.review_group_id, { decision: event.target.value as ReviewDecision })}
                                  >
                                    {allowed.map((value) => <option key={value} value={value}>{decisionLabel(value)}</option>)}
                                  </select>
                                </div>
                                <div>
                                  <label className="studio-label" htmlFor={`group-rationale-${group.review_group_id}`}>此组判断依据</label>
                                  <textarea
                                    id={`group-rationale-${group.review_group_id}`}
                                    className="studio-textarea"
                                    rows={3}
                                    value={draft.rationale}
                                    onChange={(event) => setGroupOverride(group.review_group_id, { rationale: event.target.value })}
                                    placeholder="说明为什么这一候选组与批次默认判断不同，并引用上方逐字证据。"
                                  />
                                </div>
                                <div>
                                  <label className="studio-label" htmlFor={`group-confidence-${group.review_group_id}`}>此组置信度（0–1）</label>
                                  <Input
                                    id={`group-confidence-${group.review_group_id}`}
                                    type="number"
                                    min="0"
                                    max="1"
                                    step="0.05"
                                    value={draft.confidence}
                                    onChange={(event) => setGroupOverride(group.review_group_id, { confidence: event.target.value })}
                                  />
                                </div>
                              </div>
                            ) : null}
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                ) : null}

                <Button type="submit" disabled={!canSubmit || decide.isPending}>
                  {decide.isPending ? "提交中…" : "确认并提交判断"}
                </Button>
              </form>
            )}
            {decide.error instanceof StudioApiError && decide.error.code === "canonical_identity_conflict" ? (
              <CanonicalIdentityConflictNotice error={decide.error} reviewGroups={reviewGroups} />
            ) : decide.error && errorText(decide.error) !== "已取消提交" ? (
              <p className="studio-error">{errorText(decide.error)}</p>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {item.status !== "open" && item.job_status === "needs_review" && item.job_open_resolution_reviews === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>消歧审核已全部完成</CardTitle>
            <CardDescription>所有消歧审核都已关闭；恢复仍由服务器控制平面校验，浏览器不能直接改写作业状态。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => resume.mutate()} disabled={resume.isPending}>
              {resume.isPending ? "恢复中…" : "恢复导入作业"}
            </Button>
            {resume.error && errorText(resume.error) !== "已取消恢复" ? <p className="studio-error">{errorText(resume.error)}</p> : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

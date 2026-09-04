import { useEffect, useState } from "react";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useStudioAuth } from "../../lib/studio-auth";
import type { StudioStatus } from "../../lib/studio-auth";

export default function StudioHomePage() {
  const auth = useStudioAuth();
  const [status, setStatus] = useState<StudioStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    auth
      .authedFetch("/api/v1/studio/status")
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "studio status failed");
      });
    return () => {
      cancelled = true;
    };
  }, [auth]);

  return (
    <div className="studio-grid" data-view="studio-home">
      <Card>
        <CardHeader>
          <CardTitle>Studio 总览</CardTitle>
          <CardDescription>工程操作面占位：导入、评审与语料管理在后续 C1 任务中实现。</CardDescription>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="studio-error">无法读取 Studio 状态：{error}</p>
          ) : status ? (
            <dl className="studio-facts">
              <div>
                <dt>管理员</dt>
                <dd>{status.admin_user}</dd>
              </div>
              <div>
                <dt>上游可达</dt>
                <dd>
                  <Badge>{status.upstream.reachable ? "reachable" : "unreachable"}</Badge>
                </dd>
              </div>
              <div>
                <dt>状态契约</dt>
                <dd>
                  {status.schema} {status.version}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="studio-muted">正在读取 Studio 状态…</p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>工程入口</CardTitle>
          <CardDescription>后续任务（C1-T10 导入、C1-T11 评审、C1-T13 语料）的挂载点。</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="studio-links">
            <li>
              <a href="/studio/imports">Imports — 文档导入与任务进度（占位）</a>
            </li>
            <li>
              <a href="/studio/review">Review — 跨来源评审队列（占位）</a>
            </li>
            <li>
              <a href="/studio/sources">Sources / Corpus — 来源与语料（占位）</a>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

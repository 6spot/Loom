import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
          <CardDescription>内部工程操作面；历史数据生产状态来自 Chronicle 自己的 durable control plane。</CardDescription>
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
          <CardDescription>Imports 已可操作；Review 与更丰富的 Corpus 面板按 C1 依赖继续推进。</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="studio-links">
            <li>
              <Link to="/studio/imports">Imports — 上传文献、Revision 历史、Ingestion Job 与运行进度</Link>
            </li>
            <li>
              <Link to="/studio/review">Review — 跨来源评审队列（C1-T11）</Link>
            </li>
            <li>
              <Link to="/studio/sources">Sources / Corpus — 来源与语料（后续任务）</Link>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

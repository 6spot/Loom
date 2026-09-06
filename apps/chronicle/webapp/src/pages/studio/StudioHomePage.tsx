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
        if (!cancelled) setError(err instanceof Error ? err.message : "Studio 状态读取失败");
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
                  <Badge>{status.upstream.reachable ? "可达" : "不可达"}</Badge>
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
          <CardDescription>导入、人工审核、来源语料与覆盖度均通过 Chronicle 自有接口工作。</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="studio-links">
            <li>
              <Link to="/studio/imports">导入 — 上传文献、查看版本历史、创建导入作业并跟踪进度</Link>
            </li>
            <li>
              <Link to="/studio/review">人工审核 — 处理跨来源实体与事件消歧</Link>
            </li>
            <li>
              <Link to="/studio/sources">来源 / 语料 — 管理文献来源与不可变版本</Link>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

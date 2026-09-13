import { useEffect, useRef, useState } from "react";
import { getJobResult } from "../../lib/studio-api";
import { useStudioAuth } from "../../lib/studio-auth";
import { Button } from "../ui/button";
import StructuredResult from "./StructuredResult";

export default function JobResultViewer({ jobId, sha }: { jobId: string; sha: string }) {
  const auth = useStudioAuth().authHeader();
  const [body, setBody] = useState("");
  const [offset, setOffset] = useState<number | null>(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = useRef(true);
  const loading = useRef(false);
  const load = async () => {
    if (loading.current || offset === null) return;
    loading.current = true; setBusy(true); setError("");
    try {
      const page = await getJobResult(auth, jobId, sha, offset);
      if (!current.current) return;
      if (page.job_id !== jobId || page.output_sha256 !== sha || page.offset !== offset) throw new Error("结果版本不一致，请重新打开。");
      setBody((value) => value + page.text); setOffset(page.next_offset);
    } catch (failure) { if (current.current) setError(failure instanceof Error ? failure.message : "结果读取失败"); }
    finally { loading.current = false; if (current.current) setBusy(false); }
  };
  useEffect(() => {
    current.current = true;
    void load();
    return () => { current.current = false; };
    // The caller keys this component by immutable output identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  let parsed: unknown = null;
  if (offset === null) { try { parsed = JSON.parse(body); } catch { /* Show the exact saved bytes below. */ } }
  return <div className="studio-result-viewer" aria-busy={busy}>
    {parsed ? <StructuredResult value={parsed} raw /> : body ? <pre className="studio-code">{body}</pre> : null}
    {error ? <p role="alert" className="studio-error">{error}</p> : null}
    {offset !== null ? <Button variant="outline" size="sm" disabled={busy} onClick={() => void load()}>{busy ? "正在读取…" : body ? "继续加载完整结果" : "重试读取"}</Button> : null}
  </div>;
}

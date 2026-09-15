import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ChangeEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import type {
  BackgroundAsset,
  BackgroundBinding,
  BackgroundDisplay,
  CreateBackgroundBindingInput,
  ReplaceBackgroundBindingInput,
} from "../../lib/studio-api";
import {
  backgroundAssetPreviewPath,
  backgroundMediaTypeForUpload,
  createBackgroundBinding,
  disableBackgroundBinding,
  formatShortHash,
  getBackgroundAsset,
  listBackgroundAssets,
  listBackgroundBindings,
  replaceBackgroundBinding,
  StudioApiError,
  studioBinaryRequest,
  uploadBackgroundAsset,
} from "../../lib/studio-api";
import { loadHistory, loadHistoryPage } from "../../lib/history-api";
import type { HistoryParagraph, HistoryPublication } from "../../lib/history-api";
import { useStudioAuth } from "../../lib/studio-auth";

const MAX_BACKGROUND_UPLOAD_BYTES = 8 * 1024 * 1024;

const DEFAULT_DISPLAY: BackgroundDisplay = {
  opacity: 0.35,
  position: { x: 0.5, y: 0.5 },
  scale: 1,
  mask: null,
};

type AssetStatusFilter = "all" | "candidate" | "displayed";

interface PositionOption {
  id: string;
  ordinal: number | null;
  label: string;
  excerpt: string;
  paragraph?: HistoryParagraph;
}

function cloneDisplay(value: BackgroundDisplay | null | undefined): BackgroundDisplay {
  return {
    opacity: value?.opacity ?? DEFAULT_DISPLAY.opacity,
    position: {
      x: value?.position?.x ?? DEFAULT_DISPLAY.position.x,
      y: value?.position?.y ?? DEFAULT_DISPLAY.position.y,
    },
    scale: value?.scale ?? DEFAULT_DISPLAY.scale,
    mask: value?.mask
      ? {
          ...value.mask,
        }
      : null,
  };
}

function paragraphText(paragraph: HistoryParagraph | undefined): string {
  return paragraph?.segments.map((segment) => segment.text).join("") ?? "";
}

function excerpt(value: string, length = 68): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > length ? `${compact.slice(0, length)}…` : compact;
}

function formatTime(value: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { dateStyle: "medium" });
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function statusLabel(asset: BackgroundAsset, activeUsage: number): string {
  return activeUsage > 0 ? `已展示 · ${activeUsage} 处` : asset.candidate ? "候选 · 尚未展示" : "未分类";
}

function statusFilterLabel(status: AssetStatusFilter): string {
  if (status === "displayed") return "已展示";
  if (status === "candidate") return "候选";
  return "全部";
}

function backgroundErrorText(error: unknown): string {
  if (error instanceof StudioApiError) {
    const labels: Record<string, string> = {
      overlap_conflict: "所选正文范围与已有背景重叠，请先换范围或明确替换对应位置。",
      unknown_paragraph: "所选段落不属于当前已发布 edition，请重新从正文选择。",
      unknown_edition: "当前 edition 已不可保存，请重新载入已发布历史。",
      asset_version_mismatch: "图片版本与素材不一致，请重新选择素材版本。",
      asset_file_missing: "素材文件不可用，未创建公开关联。",
      asset_file_corrupt: "素材完整性校验失败，未创建公开关联。",
      revision_conflict: "这个位置已被其他操作更新，请重新读取后再保存。",
      etag_conflict: "这个位置的版本已变化，请重新读取后再保存。",
      invalid_display: "浓淡、构图或遮罩设置不合法，请检查后再试。",
    };
    return `${labels[error.code] ?? error.message}（${error.code}）`;
  }
  if (error instanceof Error) return error.message;
  return "请求失败，请稍后重试。";
}

function positionLabel(paragraph: HistoryParagraph, publication: HistoryPublication): string {
  const group = publication.groups.find((item) => item.id === paragraph.group_id);
  const entry = publication.entry_points.find((item) => item.paragraph_id === paragraph.id);
  return [group?.label, entry?.label, excerpt(paragraphText(paragraph), 42)].filter(Boolean).join(" · ") || `正文第 ${paragraph.ordinal + 1} 段`;
}

function bindingRangeLabel(binding: BackgroundBinding, publication: HistoryPublication | null): string {
  if (publication?.version === binding.edition_version) {
    const start = publication.entry_points.find((entry) => entry.paragraph_id === binding.start_paragraph_id)?.label;
    const end = publication.entry_points.find((entry) => entry.paragraph_id === binding.end_paragraph_id)?.label;
    if (start && end && start === end) return start;
    if (start && end) return `${start} → ${end}`;
  }
  return `正文第 ${binding.start_ordinal + 1}–${binding.end_ordinal + 1} 段`;
}

function maskEdge(value: BackgroundDisplay["mask"]): number {
  return Math.max(value?.top ?? 0, value?.right ?? 0, value?.bottom ?? 0, value?.left ?? 0);
}

function PrivateImagePreview({
  auth,
  path,
  localUrl,
  alt,
  className,
  style,
}: {
  auth: string | null;
  path: string | null;
  localUrl?: string | null;
  alt: string;
  className?: string;
  style?: CSSProperties;
}) {
  const [imageUrl, setImageUrl] = useState<string | null>(localUrl ?? null);
  const [loading, setLoading] = useState(Boolean(path) && !localUrl);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (localUrl) {
      setImageUrl(localUrl);
      setLoading(false);
      setError(null);
      return;
    }
    if (!path) {
      setImageUrl(null);
      setLoading(false);
      setError(null);
      return;
    }
    let alive = true;
    let objectUrl: string | null = null;
    setImageUrl(null);
    setLoading(true);
    setError(null);
    void studioBinaryRequest(auth, path)
      .then((blob) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!alive) return;
        setLoading(false);
        setError(backgroundErrorText(reason));
      });
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [auth, localUrl, path]);

  if (imageUrl) return <img className={className} style={style} src={imageUrl} alt={alt} />;
  if (loading) return <div className="studio-background-image-state" role="status">正在读取预览…</div>;
  if (error) return <div className="studio-background-image-state studio-background-image-error" role="alert">预览不可用：{error}</div>;
  return <div className="studio-background-image-state">尚未选择图片</div>;
}

export default function StudioBackgroundsPage() {
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const requestedVersion = searchParams.get("version");
  const requestedParagraph = searchParams.get("paragraph_id") ?? searchParams.get("paragraph");
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [era, setEra] = useState("");
  const [prompt, setPrompt] = useState("");
  const [search, setSearch] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [filterEra, setFilterEra] = useState("");
  const [assetStatus, setAssetStatus] = useState<AssetStatusFilter>("all");
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const [selectedAssetVersionId, setSelectedAssetVersionId] = useState<string | null>(null);
  const [selectedBindingId, setSelectedBindingId] = useState<string | null>(null);
  const [startParagraphId, setStartParagraphId] = useState("");
  const [endParagraphId, setEndParagraphId] = useState("");
  const [pageStart, setPageStart] = useState(0);
  const [pageAt, setPageAt] = useState<string | null>(requestedParagraph);
  const [loadedParagraphs, setLoadedParagraphs] = useState<Record<string, HistoryParagraph>>({});
  const [displayDraft, setDisplayDraft] = useState<BackgroundDisplay>(cloneDisplay(DEFAULT_DISPLAY));
  const [showBackground, setShowBackground] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  const assets = useQuery({
    queryKey: ["studio", "background-assets", "all"],
    queryFn: () => listBackgroundAssets(authHeader, { limit: 100 }),
    staleTime: 10_000,
  });
  const bindings = useQuery({
    queryKey: ["studio", "background-bindings", "all"],
    queryFn: () => listBackgroundBindings(authHeader, { status: "all", limit: 100 }),
    staleTime: 5_000,
  });
  const history = useQuery({
    queryKey: ["studio", "background-history", requestedVersion ?? "latest"],
    queryFn: () => loadHistory(requestedVersion),
    staleTime: Infinity,
  });
  const historyVersion = history.data?.version ?? null;
  const historyPage = useQuery({
    queryKey: ["studio", "background-history-page", historyVersion, pageAt ?? `start:${pageStart}`],
    queryFn: () => loadHistoryPage(historyVersion as string, pageAt ? { at: pageAt } : { start: pageStart }),
    enabled: Boolean(historyVersion),
    staleTime: Infinity,
  });
  const endPage = useQuery({
    queryKey: ["studio", "background-history-end", historyVersion, endParagraphId],
    queryFn: () => loadHistoryPage(historyVersion as string, { at: endParagraphId }),
    enabled: Boolean(historyVersion && endParagraphId && endParagraphId !== startParagraphId),
    staleTime: Infinity,
  });
  const selectedAsset = useQuery({
    queryKey: ["studio", "background-asset", selectedAssetId, selectedAssetVersionId],
    queryFn: () => getBackgroundAsset(authHeader, selectedAssetId as string, selectedAssetVersionId),
    enabled: Boolean(selectedAssetId && selectedAssetVersionId),
    staleTime: Infinity,
  });

  useEffect(() => {
    const paragraphs = historyPage.data?.paragraphs ?? [];
    if (!paragraphs.length) return;
    setLoadedParagraphs((current) => {
      const next = { ...current };
      for (const paragraph of paragraphs) next[paragraph.id] = paragraph;
      return next;
    });
    const first = paragraphs[0];
    setStartParagraphId((current) => current || first.id);
    setEndParagraphId((current) => current || requestedParagraph || first.id);
  }, [historyPage.data, requestedParagraph]);

  useEffect(() => {
    const paragraphs = endPage.data?.paragraphs ?? [];
    if (!paragraphs.length) return;
    setLoadedParagraphs((current) => {
      const next = { ...current };
      for (const paragraph of paragraphs) next[paragraph.id] = paragraph;
      return next;
    });
  }, [endPage.data]);

  const activeBindingCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const binding of bindings.data?.bindings ?? []) {
      if (binding.active) counts.set(binding.asset_id, (counts.get(binding.asset_id) ?? 0) + 1);
    }
    return counts;
  }, [bindings.data]);

  const sourceOptions = useMemo(
    () => [...new Set((assets.data?.assets ?? []).map((asset) => asset.source).filter((value): value is string => Boolean(value)))].sort(),
    [assets.data],
  );
  const eraOptions = useMemo(
    () => [...new Set((assets.data?.assets ?? []).map((asset) => asset.era).filter((value): value is string => Boolean(value)))].sort(),
    [assets.data],
  );
  const filteredAssets = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return (assets.data?.assets ?? []).filter((asset) => {
      const usage = activeBindingCounts.get(asset.asset_id) ?? 0;
      if (assetStatus === "displayed" && usage === 0) return false;
      if (assetStatus === "candidate" && usage > 0) return false;
      if (filterSource && asset.source !== filterSource) return false;
      if (filterEra && asset.era !== filterEra) return false;
      if (!needle) return true;
      return [asset.filename, asset.source, asset.era, asset.prompt]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase().includes(needle));
    });
  }, [activeBindingCounts, assetStatus, assets.data, filterEra, filterSource, search]);
  const selectedBinding = useMemo(
    () => bindings.data?.bindings.find((binding) => binding.binding_id === selectedBindingId) ?? null,
    [bindings.data, selectedBindingId],
  );
  const listedAsset = assets.data?.assets.find((asset) => asset.asset_id === selectedAssetId) ?? null;
  const editorAsset = selectedAsset.data ?? selectedBinding?.asset ?? listedAsset;
  const localPreviewUrl = useLocalFileUrl(file);
  const positionOptions = useMemo(() => {
    const options: PositionOption[] = Object.values(loadedParagraphs)
      .sort((left, right) => left.ordinal - right.ordinal)
      .map<PositionOption>((paragraph) => ({
        id: paragraph.id,
        ordinal: paragraph.ordinal,
        label: history.data ? positionLabel(paragraph, history.data) : `正文第 ${paragraph.ordinal + 1} 段`,
        excerpt: excerpt(paragraphText(paragraph), 120),
        paragraph,
      }));
    const existing = new Set(options.map((option) => option.id));
    for (const [id, ordinal, label] of [
      [startParagraphId, selectedBinding?.start_ordinal ?? null, "已保存的范围起点"],
      [endParagraphId, selectedBinding?.end_ordinal ?? null, "已保存的范围终点"],
    ] as Array<[string, number | null, string]>) {
      if (id && !existing.has(id)) options.push({ id, ordinal, label, excerpt: "载入此段以查看正文上下文" });
    }
    return options.sort((left, right) => (left.ordinal ?? Number.MAX_SAFE_INTEGER) - (right.ordinal ?? Number.MAX_SAFE_INTEGER));
  }, [endParagraphId, history.data, loadedParagraphs, selectedBinding, startParagraphId]);
  const startOption = positionOptions.find((option) => option.id === startParagraphId);
  const endOption = positionOptions.find((option) => option.id === endParagraphId);
  const previewParagraphs = useMemo(() => {
    const start = startOption?.ordinal;
    const end = endOption?.ordinal;
    if (start == null || end == null) return [];
    return Object.values(loadedParagraphs)
      .filter((paragraph) => paragraph.ordinal >= start && paragraph.ordinal <= end)
      .sort((left, right) => left.ordinal - right.ordinal)
      .slice(0, 8);
  }, [endOption?.ordinal, loadedParagraphs, startOption?.ordinal]);
  const rangeReady = Boolean(historyVersion && startParagraphId && endParagraphId && startOption?.ordinal != null && endOption?.ordinal != null && startOption.ordinal <= endOption.ordinal);
  const previewImagePath = editorAsset ? backgroundAssetPreviewPath(editorAsset.asset_id, editorAsset.asset_version_id) : null;
  const imageStyle: CSSProperties = {
    opacity: showBackground ? displayDraft.opacity : 0,
    objectPosition: `${displayDraft.position.x * 100}% ${displayDraft.position.y * 100}%`,
    transform: `scale(${displayDraft.scale})`,
  };
  const maskStyle = displayDraft.mask
    ? {
        top: `${(displayDraft.mask.top ?? 0) * 100}%`,
        right: `${(displayDraft.mask.right ?? 0) * 100}%`,
        bottom: `${(displayDraft.mask.bottom ?? 0) * 100}%`,
        left: `${(displayDraft.mask.left ?? 0) * 100}%`,
      }
    : undefined;

  const resetEditorFeedback = () => {
    setNotice(null);
    saveMutation.reset();
    disableMutation.reset();
  };
  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new StudioApiError(400, "missing_file", "请选择一张 PNG、JPEG 或 WebP 图片。");
      if (!backgroundMediaTypeForUpload(file.name)) throw new StudioApiError(400, "unsupported_file", "只支持 PNG、JPEG 或 WebP 图片。");
      if (file.size > MAX_BACKGROUND_UPLOAD_BYTES) throw new StudioApiError(413, "payload_too_large", "图片不能超过 8 MiB。");
      return uploadBackgroundAsset(authHeader, file, { source, era, prompt });
    },
    onSuccess: async (asset) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "background-assets"] });
      setSelectedAssetId(asset.asset_id);
      setSelectedAssetVersionId(asset.asset_version_id);
      setSelectedBindingId(null);
      setDisplayDraft(cloneDisplay(DEFAULT_DISPLAY));
      setNotice("图片已上传为候选素材。它还没有公开展示；请在下方预览并明确保存。");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    },
  });
  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!editorAsset) throw new StudioApiError(400, "missing_asset", "请先选择候选素材。");
      if (!historyVersion) throw new StudioApiError(400, "missing_edition", "当前没有可保存的已发布历史 edition。");
      if (!rangeReady) throw new StudioApiError(400, "invalid_paragraph_range", "请选择同一已发布正文中的有效起止范围。");
      const common = {
        asset_id: editorAsset.asset_id,
        asset_version_id: editorAsset.asset_version_id,
        display: cloneDisplay(displayDraft),
        actor: auth.username,
      };
      if (selectedBinding) {
        const input: ReplaceBackgroundBindingInput = {
          ...common,
          start_paragraph_id: startParagraphId,
          end_paragraph_id: endParagraphId,
          expected_revision: selectedBinding.revision,
          expected_etag: selectedBinding.etag,
        };
        return replaceBackgroundBinding(authHeader, selectedBinding.binding_id, input);
      }
      const input: CreateBackgroundBindingInput = {
        ...common,
        edition_version: historyVersion,
        start_paragraph_id: startParagraphId,
        end_paragraph_id: endParagraphId,
      };
      return createBackgroundBinding(authHeader, input);
    },
    onSuccess: async (binding) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "background-bindings"] });
      setSelectedBindingId(binding.binding_id);
      setSelectedAssetId(binding.asset_id);
      setSelectedAssetVersionId(binding.asset_version_id);
      setNotice(`已保存并显示：${bindingRangeLabel(binding, history.data ?? null)}。公开读取现在只会命中这段精确范围。`);
    },
  });
  const disableMutation = useMutation({
    mutationFn: async (binding?: BackgroundBinding) => {
      const target = binding ?? selectedBinding;
      if (!target) throw new StudioApiError(400, "missing_binding", "请选择一个已保存的背景关联。");
      return disableBackgroundBinding(authHeader, target.binding_id, {
        actor: auth.username,
        expected_revision: target.revision,
        expected_etag: target.etag,
      });
    },
    onSuccess: async (binding) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "background-bindings"] });
      setNotice(`已停用 ${bindingRangeLabel(binding, history.data ?? null)} 的背景关联；其他位置不受影响。`);
    },
  });

  const chooseAsset = (asset: BackgroundAsset) => {
    resetEditorFeedback();
    setSelectedAssetId(asset.asset_id);
    setSelectedAssetVersionId(asset.asset_version_id);
    setSelectedBindingId(null);
    setDisplayDraft(cloneDisplay(DEFAULT_DISPLAY));
  };
  const chooseBinding = (binding: BackgroundBinding) => {
    resetEditorFeedback();
    setSelectedBindingId(binding.binding_id);
    setSelectedAssetId(binding.asset_id);
    setSelectedAssetVersionId(binding.asset_version_id);
    setStartParagraphId(binding.start_paragraph_id);
    setEndParagraphId(binding.end_paragraph_id);
    setDisplayDraft(cloneDisplay(binding.display));
    setPageAt(binding.start_paragraph_id);
    setPageStart(0);
  };
  const updatePosition = (which: "start" | "end", event: ChangeEvent<HTMLSelectElement>) => {
    resetEditorFeedback();
    const value = event.target.value;
    if (which === "start") {
      setStartParagraphId(value);
      const nextStart = positionOptions.find((option) => option.id === value)?.ordinal;
      const currentEnd = positionOptions.find((option) => option.id === endParagraphId)?.ordinal;
      if (nextStart != null && (currentEnd == null || nextStart > currentEnd)) setEndParagraphId(value);
    } else {
      setEndParagraphId(value);
    }
  };
  const changeFile = (next: File | null) => {
    uploadMutation.reset();
    setNotice(null);
    setFile(next);
  };

  return (
    <div className="studio-stack" data-view="studio-backgrounds">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">C3 · 人工确认的视觉层</p>
          <h1>背景素材库</h1>
          <p className="studio-muted">上传只是候选。只有在正文范围和效果都确认后，“保存并显示”才会创建公开关联。</p>
        </div>
        <Link className="studio-link-button" to="/history">打开读者历史 →</Link>
      </div>

      {notice ? <p className="studio-success" role="status">{notice}</p> : null}

      <section className="studio-panel studio-background-upload" aria-labelledby="background-upload-title">
        <div className="studio-section-heading">
          <div><h2 id="background-upload-title">上传候选图片</h2><p className="studio-muted">支持 PNG / JPEG / WebP，单文件最多 8 MiB。上传完成不会自动展示。</p></div>
          <span className="studio-status" data-status="needs_review">待人工确认</span>
        </div>
        <form onSubmit={(event) => { event.preventDefault(); if (!uploadMutation.isPending) uploadMutation.mutate(); }}>
          <fieldset className="studio-background-upload-fields" disabled={uploadMutation.isPending}>
            <label className={`studio-dropzone studio-background-dropzone ${file ? "has-file" : ""}`}>
              <span aria-hidden="true">↥</span>
              <strong>{file?.name ?? "选择图片，或拖到这里"}</strong>
              <small>{file ? `${formatBytes(file.size)} · ${backgroundMediaTypeForUpload(file.name) ?? "格式待校验"}` : "实际解码格式、尺寸和完整性由服务端再次核验"}</small>
              <input
                ref={fileInput}
                type="file"
                accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp"
                aria-label="选择背景图片"
                onChange={(event) => changeFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <div className="studio-form studio-background-upload-form">
              <label>素材来源<Input value={source} onChange={(event) => setSource(event.target.value)} placeholder="例如：skill 归档 / 操作员上传" /></label>
              <label>历史时期<Input value={era} onChange={(event) => setEra(event.target.value)} placeholder="例如：东汉末年" /></label>
              <label>制作提示词 / 说明<textarea className="studio-input studio-background-textarea" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} placeholder="保留实际制作信息，便于复用和核对" /></label>
              {uploadMutation.error ? <p className="studio-error" role="alert">上传未完成：{backgroundErrorText(uploadMutation.error)}</p> : null}
              <Button type="submit" disabled={!file || uploadMutation.isPending}>{uploadMutation.isPending ? "正在校验并上传…" : "上传为候选"}</Button>
            </div>
          </fieldset>
        </form>
      </section>

      <section className="studio-background-library" aria-labelledby="background-library-title">
        <aside className="studio-panel studio-background-filters">
          <div className="studio-section-heading"><div><h2 id="background-library-title">素材库</h2><p className="studio-muted">按时代、来源和实际使用状态查找。</p></div><span className="studio-muted">{assets.data?.assets.length ?? "—"}</span></div>
          <label className="studio-background-filter-label">搜索素材<Input aria-label="搜索背景素材" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="文件名、来源、时期或说明" /></label>
          <label className="studio-background-filter-label">来源<select className="studio-select" value={filterSource} onChange={(event) => setFilterSource(event.target.value)}><option value="">全部来源</option>{sourceOptions.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
          <label className="studio-background-filter-label">时代<select className="studio-select" value={filterEra} onChange={(event) => setFilterEra(event.target.value)}><option value="">全部时代</option>{eraOptions.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
          <div className="studio-segmented studio-background-status-filter" role="group" aria-label="素材使用状态">{(["all", "candidate", "displayed"] as const).map((value) => <button type="button" key={value} aria-pressed={assetStatus === value} onClick={() => setAssetStatus(value)}>{statusFilterLabel(value)}</button>)}</div>
          <p className="studio-background-private-note">候选预览使用受鉴权的 Studio 请求；未保存图片不会被普通读者读取。</p>
        </aside>
        <div className="studio-panel studio-background-asset-panel">
          <div className="studio-section-heading"><div><h2>候选与已使用素材</h2><p className="studio-muted">卡片上的“已展示”只来自 active binding，不代表上传本身已发布。</p></div><Button variant="outline" size="sm" onClick={() => void Promise.all([assets.refetch(), bindings.refetch()])} disabled={assets.isFetching || bindings.isFetching}>{assets.isFetching || bindings.isFetching ? "刷新中…" : "刷新素材库"}</Button></div>
          {assets.error ? <p className="studio-error" role="alert">素材库读取失败：{backgroundErrorText(assets.error)}</p> : null}
          {assets.isPending ? <p className="studio-muted">正在读取素材库…</p> : null}
          {!assets.isPending && filteredAssets.length === 0 ? <div className="studio-empty"><strong>没有符合条件的素材</strong><p>可以调整筛选条件，或上传一张新的候选图片。</p></div> : null}
          <div className="studio-background-asset-grid">
            {filteredAssets.map((asset) => {
              const usage = activeBindingCounts.get(asset.asset_id) ?? 0;
              const selected = selectedAssetId === asset.asset_id && !selectedBindingId;
              return <article className={`studio-background-asset-card ${selected ? "is-selected" : ""}`} key={asset.asset_id}>
                <button type="button" className="studio-background-asset-select" aria-pressed={selected} onClick={() => chooseAsset(asset)}>
                  <span className="studio-background-thumb"><PrivateImagePreview auth={authHeader} path={backgroundAssetPreviewPath(asset.asset_id, asset.asset_version_id)} alt={`${asset.era ?? "历史"}背景候选预览`} /></span>
                  <span className="studio-background-asset-status studio-status" data-status={usage > 0 ? "completed" : "needs_review"}>{statusLabel(asset, usage)}</span>
                  <strong>{asset.filename}</strong>
                  <small>{asset.era || "时代未填写"} · {asset.source || "来源未填写"}</small>
                  <small>{asset.width} × {asset.height} · {formatBytes(asset.byte_size)} · v{asset.version}</small>
                </button>
                <details className="studio-details studio-background-asset-details"><summary>制作信息</summary><dl className="studio-facts"><div><dt>来源</dt><dd>{asset.source || "—"}</dd></div><div><dt>提示词</dt><dd>{asset.prompt || "—"}</dd></div><div><dt>上传时间</dt><dd>{formatTime(asset.created_at)}</dd></div><div><dt>校验值</dt><dd className="studio-mono">{formatShortHash(asset.content_sha256)}</dd></div></dl></details>
              </article>;
            })}
          </div>
          {assets.data?.has_more ? <p className="studio-muted">素材超过当前 100 项，请缩小来源或时代范围后继续查找。</p> : null}
        </div>
      </section>

      <section className="studio-panel studio-background-editor" aria-labelledby="background-editor-title">
        <div className="studio-section-heading">
          <div><p className="studio-eyebrow">选择具体正文位置</p><h2 id="background-editor-title">预览与保存关联</h2><p className="studio-muted">所有调整都留在当前 Studio 草稿中；成功响应前不会改变读者页面。</p></div>
          {selectedBinding ? <span className="studio-status" data-status={selectedBinding.active ? "completed" : "failed"}>{selectedBinding.active ? "正在编辑已展示关联" : "已停用，可重新保存"}</span> : <span className="studio-status" data-status="needs_review">新关联草稿</span>}
        </div>
        <div className="studio-background-editor-grid">
          <section className="studio-background-location" aria-labelledby="background-location-title">
            <div className="studio-section-heading"><div><h3 id="background-location-title">正文位置</h3><p className="studio-muted">从已发布 edition 的可读段落选择范围。</p></div></div>
            {history.isPending ? <p className="studio-muted">正在读取当前已发布历史…</p> : null}
            {history.error ? <p className="studio-error" role="alert">历史正文读取失败：{backgroundErrorText(history.error)}</p> : null}
            {!history.isPending && !history.error && !history.data ? <p className="studio-error" role="alert">当前没有已发布历史 edition，先发布正文后才能保存背景。</p> : null}
            {history.data ? <>
              <div className="studio-background-edition-summary"><strong>{history.data.title || "当前已发布历史"}</strong><span>{history.data.paragraph_count.toLocaleString()} 段正文 · {formatShortHash(history.data.version)}</span></div>
              <div className="studio-background-position-fields">
                <label>范围起点<select className="studio-select" value={startParagraphId} onChange={(event) => updatePosition("start", event)} aria-label="背景范围起点"><option value="">选择起点…</option>{positionOptions.map((option) => <option value={option.id} key={`start:${option.id}`}>{option.label}</option>)}</select></label>
                <label>范围终点<select className="studio-select" value={endParagraphId} onChange={(event) => updatePosition("end", event)} aria-label="背景范围终点"><option value="">选择终点…</option>{positionOptions.map((option) => <option value={option.id} key={`end:${option.id}`}>{option.label}</option>)}</select></label>
              </div>
              <div className="studio-background-page-controls"><Button variant="outline" size="sm" disabled={!historyPage.data?.previous_start || historyPage.isFetching} onClick={() => { setPageAt(null); setPageStart(historyPage.data?.previous_start ?? 0); }}>← 上一页</Button><span>{historyPage.data ? `第 ${historyPage.data.start + 1}–${historyPage.data.start + historyPage.data.paragraphs.length} 段` : "正在读取段落"}</span><Button variant="outline" size="sm" disabled={!historyPage.data?.next_start || historyPage.isFetching} onClick={() => { setPageAt(null); setPageStart(historyPage.data?.next_start ?? 0); }}>下一页 →</Button></div>
              {historyPage.error ? <p className="studio-error" role="alert">段落读取失败：{backgroundErrorText(historyPage.error)}</p> : null}
              {rangeReady ? <p className="studio-background-range-summary">当前范围：第 {(startOption?.ordinal ?? 0) + 1}–{(endOption?.ordinal ?? 0) + 1} 段 · {previewParagraphs.length ? "已载入正文预览" : "正在载入正文预览"}</p> : <p className="studio-error">请先选择有效的起止段落。</p>}
              <details className="studio-details"><summary>位置技术详情</summary><dl className="studio-facts"><div><dt>edition</dt><dd className="studio-mono">{history.data.version}</dd></div><div><dt>起点 ID</dt><dd className="studio-mono">{startParagraphId || "—"}</dd></div><div><dt>终点 ID</dt><dd className="studio-mono">{endParagraphId || "—"}</dd></div></dl></details>
            </> : null}
          </section>

          <section className="studio-background-preview-column" aria-labelledby="background-preview-title">
            <div className="studio-section-heading"><div><h3 id="background-preview-title">正文与背景预览</h3><p className="studio-muted">仅管理员可见的临时叠加，不会发起公开关联。</p></div><label className="studio-background-toggle"><input type="checkbox" checked={showBackground} onChange={(event) => setShowBackground(event.target.checked)} />显示背景</label></div>
            <div className="studio-background-preview" data-background-visible={showBackground ? "true" : "false"}>
              {editorAsset ? <PrivateImagePreview auth={authHeader} path={previewImagePath} localUrl={localPreviewUrl} alt="背景预览" className="studio-background-preview-image" style={imageStyle} /> : null}
              {displayDraft.mask ? <div className={`studio-background-mask studio-background-mask-${displayDraft.mask.shape ?? "gradient"}`} style={maskStyle} aria-hidden="true" /> : null}
              <div className="studio-background-preview-copy">
                {editorAsset ? <p className="studio-background-preview-caption">{editorAsset.era || "未标注时代"} · v{editorAsset.version} · 候选预览</p> : <p className="studio-muted">选择一张素材后在此检查正文可读性。</p>}
                {previewParagraphs.length ? previewParagraphs.map((paragraph) => <p key={paragraph.id}>{paragraphText(paragraph)}</p>) : <p className="studio-muted">请选择正文范围。正文会在这里以实际内容预览。</p>}
                {previewParagraphs.length >= 8 ? <small className="studio-muted">预览已截取 8 段；保存范围仍以起止段落为准。</small> : null}
              </div>
            </div>
            {editorAsset ? <p className="studio-background-preview-meta">{editorAsset.filename} · {editorAsset.width} × {editorAsset.height} · {statusLabel(editorAsset, activeBindingCounts.get(editorAsset.asset_id) ?? 0)}</p> : null}
          </section>

          <section className="studio-background-controls" aria-labelledby="background-controls-title">
            <div className="studio-section-heading"><div><h3 id="background-controls-title">显示设置</h3><p className="studio-muted">保存的数值会随 binding 返回，阅读层不会自行修改。</p></div></div>
            <label>浓淡 <output htmlFor="background-opacity">{Math.round(displayDraft.opacity * 100)}%</output><input id="background-opacity" type="range" min="0" max="1" step="0.01" value={displayDraft.opacity} onChange={(event) => { resetEditorFeedback(); setDisplayDraft((current) => ({ ...current, opacity: Number(event.target.value) })); }} /></label>
            <label>主体横向位置 <output htmlFor="background-position-x">{Math.round(displayDraft.position.x * 100)}%</output><input id="background-position-x" type="range" min="0" max="1" step="0.01" value={displayDraft.position.x} onChange={(event) => { resetEditorFeedback(); setDisplayDraft((current) => ({ ...current, position: { ...current.position, x: Number(event.target.value) } })); }} /></label>
            <label>主体纵向位置 <output htmlFor="background-position-y">{Math.round(displayDraft.position.y * 100)}%</output><input id="background-position-y" type="range" min="0" max="1" step="0.01" value={displayDraft.position.y} onChange={(event) => { resetEditorFeedback(); setDisplayDraft((current) => ({ ...current, position: { ...current.position, y: Number(event.target.value) } })); }} /></label>
            <label>构图缩放 <output htmlFor="background-scale">{displayDraft.scale.toFixed(1)}×</output><input id="background-scale" type="range" min="0.1" max="4" step="0.1" value={displayDraft.scale} onChange={(event) => { resetEditorFeedback(); setDisplayDraft((current) => ({ ...current, scale: Number(event.target.value) })); }} /></label>
            <label>正文遮罩<select className="studio-select" value={displayDraft.mask?.shape ?? "none"} onChange={(event) => { resetEditorFeedback(); const shape = event.target.value as "none" | "rect" | "gradient"; setDisplayDraft((current) => ({ ...current, mask: shape === "none" ? null : { shape, top: 0.12, right: 0.08, bottom: 0.12, left: 0.08 } })); }}><option value="none">不使用遮罩</option><option value="gradient">边缘渐变遮罩</option><option value="rect">正文安全区遮罩</option></select></label>
            {displayDraft.mask ? <label>遮罩边缘 <output htmlFor="background-mask-edge">{Math.round(maskEdge(displayDraft.mask) * 100)}%</output><input id="background-mask-edge" type="range" min="0" max="0.45" step="0.01" value={maskEdge(displayDraft.mask)} onChange={(event) => { resetEditorFeedback(); const edge = Number(event.target.value); setDisplayDraft((current) => ({ ...current, mask: current.mask ? { ...current.mask, top: edge, right: edge, bottom: edge, left: edge } : null })); }} /></label> : null}
            <p className="studio-background-control-note">预览开关只影响当前 Studio 面板。关闭背景、保存失败或冲突时，当前候选、范围和这些设置都会保留。</p>
          </section>
        </div>
        {saveMutation.error ? <p className="studio-error" role="alert">保存未完成：{backgroundErrorText(saveMutation.error)} 当前选择和草稿仍保留，未提示已启用。</p> : null}
        {disableMutation.error ? <p className="studio-error" role="alert">停用未完成：{backgroundErrorText(disableMutation.error)} 当前关联状态仍以服务端为准。</p> : null}
        <div className="studio-review-actionbar studio-background-actionbar">
          <div className="studio-review-actionbar-status"><strong>{selectedBinding?.active ? "已选中一个 active 关联" : "尚未创建公开关联"}</strong><span>{editorAsset ? ` · ${editorAsset.filename}` : " · 请选择素材"}</span></div>
          <div className="studio-review-actionbar-buttons"><Button variant="outline" onClick={() => { resetEditorFeedback(); setSelectedBindingId(null); setSelectedAssetId(null); setSelectedAssetVersionId(null); setDisplayDraft(cloneDisplay(DEFAULT_DISPLAY)); }}>清空草稿</Button>{selectedBinding?.active ? <Button variant="destructive" disabled={disableMutation.isPending || saveMutation.isPending} onClick={() => disableMutation.mutate()}>{disableMutation.isPending ? "停用中…" : "停用此处"}</Button> : null}<Button size="lg" disabled={saveMutation.isPending || disableMutation.isPending || !editorAsset || !rangeReady || !historyVersion} onClick={() => saveMutation.mutate()}>{saveMutation.isPending ? "正在保存…" : selectedBinding ? "保存替换并显示" : "保存并显示"}</Button></div>
        </div>
      </section>

      <section className="studio-panel studio-background-bindings" aria-labelledby="background-bindings-title">
        <div className="studio-section-heading"><div><h2 id="background-bindings-title">已保存的具体位置</h2><p className="studio-muted">每一行都是独立关联；同一张图可以复用，替换或停用一处不会改动其他位置。</p></div><span className="studio-muted">{bindings.data?.bindings.length ?? "—"}</span></div>
        {bindings.error ? <p className="studio-error" role="alert">已保存关联读取失败：{backgroundErrorText(bindings.error)}</p> : null}
        {bindings.isPending ? <p className="studio-muted">正在读取已保存关联…</p> : null}
        {!bindings.isPending && bindings.data?.bindings.length === 0 ? <div className="studio-empty"><strong>还没有公开背景关联</strong><p>候选素材只有在“保存并显示”成功后才会出现在这里。</p></div> : null}
        <div className="studio-background-binding-list">
          {bindings.data?.bindings.map((binding) => <article className={`studio-background-binding-row ${selectedBindingId === binding.binding_id ? "is-selected" : ""}`} key={binding.binding_id}>
            <button type="button" className="studio-background-binding-select" aria-pressed={selectedBindingId === binding.binding_id} onClick={() => chooseBinding(binding)}>
              <span className="studio-background-binding-icon" aria-hidden="true">图</span>
              <span><strong>{bindingRangeLabel(binding, history.data ?? null)}</strong><small>{binding.active ? "读者可读 · " : "已停用 · "}{binding.asset.filename} · v{binding.asset_version} · {binding.edition_version === historyVersion ? "当前 edition" : "其他 edition"}</small></span>
              <span className="studio-status" data-status={binding.active ? "completed" : "failed"}>{binding.active ? "已展示" : "已停用"}</span>
            </button>
            <div className="studio-background-binding-actions">{binding.active ? <Button variant="outline" size="sm" onClick={() => { chooseBinding(binding); disableMutation.mutate(binding); }}>停用</Button> : <Button variant="outline" size="sm" onClick={() => chooseBinding(binding)}>重新编辑</Button>}<details className="studio-details"><summary>详情</summary><dl className="studio-facts"><div><dt>范围</dt><dd>第 {binding.start_ordinal + 1}–{binding.end_ordinal + 1} 段</dd></div><div><dt>版本</dt><dd>{binding.revision} · {binding.etag}</dd></div><div><dt>保存时间</dt><dd>{formatTime(binding.updated_at)}</dd></div><div><dt>binding ID</dt><dd className="studio-mono">{binding.binding_id}</dd></div></dl></details></div>
          </article>)}
        </div>
        {bindings.data?.has_more ? <p className="studio-muted">只显示最近 100 条关联；可按正文范围缩小后端查询。</p> : null}
      </section>

      <p className="studio-system-status"><span data-status="completed" />本页面只上传、预览和保存人工确认的素材，不调用图片生成模型。</p>
    </div>
  );
}

function useLocalFileUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== "function") {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}

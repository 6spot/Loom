import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getModelOptions, type ModelSelection } from "../../lib/studio-api";
import { useStudioAuth } from "../../lib/studio-auth";
import { PRODUCTION_STEPS } from "../../lib/studio-workspace";
import { Button } from "../ui/button";

export default function ModelSelector({ value, onChange, onReady, disabled = false }: {
  value?: ModelSelection; onChange: (value: ModelSelection | undefined) => void; onReady?: (ready: boolean) => void; disabled?: boolean;
}) {
  const auth = useStudioAuth().authHeader();
  const options = useQuery({ queryKey: ["studio", "model-options"], queryFn: () => getModelOptions(auth), staleTime: 30_000 });
  const data = options.data;
  useEffect(() => {
    if (!value && data?.available && data.config_sha256) onChange({ config_sha256: data.config_sha256, steps: data.steps });
  }, [data, value, onChange]);
  const stale = value && data && value.config_sha256 !== data.config_sha256;
  const ready = !options.isPending && !options.isError && !stale && Boolean(data && (!data.available || value));
  useEffect(() => { onReady?.(ready); }, [onReady, ready]);
  const steps = value?.steps ?? data?.steps;
  return <div className="studio-model-settings">
    {options.isPending ? <p className="studio-muted">正在读取模型配置…</p> : null}
    {options.isError ? <p role="alert" className="studio-error">模型配置读取失败。<Button variant="ghost" size="sm" onClick={() => void options.refetch()}>重新读取</Button></p> : null}
    {stale ? <p role="alert" className="studio-error">配置已更新，请重新选择模型。<Button size="sm" variant="outline" disabled={disabled} onClick={() => onChange(undefined)}>使用当前配置</Button></p> : null}
    {data?.available && steps ? <>
      <div className="studio-row-title"><strong>处理模型</strong><span className="studio-muted">{data.models.filter((model) => steps.translation?.includes(model.id)).map((model) => model.name).join("、")}</span></div>
      <details><summary>调整各步骤模型</summary>
        <p className="studio-muted">每步可选择 1–4 个已配置模型。多份结果会分别保存，再进行比较；整章翻译与信息提取可同时进行。</p>
        <div className="studio-model-grid">{PRODUCTION_STEPS.map((step) => <fieldset key={step.id} disabled={disabled || Boolean(stale)}>
          <legend>{step.label}</legend>
          {data.models.map((model, index) => {
            const selected = steps[step.id] ?? [];
            return <label key={model.id}><input type="checkbox" checked={selected.includes(model.id)}
              disabled={selected.includes(model.id) ? selected.length === 1 : selected.length >= 4}
              onChange={() => onChange({ config_sha256: data.config_sha256!, steps: { ...steps,
                [step.id]: selected.includes(model.id) ? selected.filter((id) => id !== model.id) : [...selected, model.id],
              } })} />{model.name}{data.models.filter((entry) => entry.name === model.name).length > 1 ? <small>配置 {index + 1}</small> : null}</label>;
          })}
        </fieldset>)}</div>
        <p className="studio-muted">超时与重试预算沿用系统统一配置，当前任务创建后固定。</p>
      </details>
    </> : data ? <p className="studio-muted">沿用服务端处理配置。配置可选模型后，可在这里分步骤选择。</p> : null}
  </div>;
}

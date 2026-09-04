import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

function Placeholder({ title, description, next }: { title: string; description: string; next: string }) {
  return (
    <Card data-view={`studio-${title.toLowerCase()}`}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="studio-muted">{next}</p>
      </CardContent>
    </Card>
  );
}

export function ImportsPage() {
  return (
    <Placeholder
      title="Imports"
      description="文档上传与导入任务进度。C1-T9 只提供工程占位，不实现任务逻辑。"
      next="后续 C1-T10 在此挂载文档/导入操作与进度查询；当前版本不调用任何特权 API。"
    />
  );
}

export function ReviewPage() {
  return (
    <Placeholder
      title="Review"
      description="跨来源 resolution 评审队列。C1-T9 只提供工程占位，不实现评审工作流。"
      next="后续 C1-T11 在此挂载评审队列；当前版本不调用任何特权 API。"
    />
  );
}

export function SourcesPage() {
  return (
    <Placeholder
      title="Sources / Corpus"
      description="来源与语料可见性。C1-T9 只提供工程占位。"
      next="后续 C1-T12/C1-T13 在此挂载 Reader Presentation 与语料包；当前版本不调用任何特权 API。"
    />
  );
}

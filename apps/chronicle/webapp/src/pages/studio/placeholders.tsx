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

export function ReviewPage() {
  return (
    <Placeholder
      title="Review"
      description="跨来源 resolution 评审队列。C1-T9 只提供工程占位，不实现评审工作流。"
      next="后续 C1-T11 在此挂载评审队列；当前版本不调用任何特权 API。"
    />
  );
}

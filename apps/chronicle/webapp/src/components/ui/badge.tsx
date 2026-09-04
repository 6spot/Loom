// shadcn/ui-style Badge (Studio only).
import type { HTMLAttributes } from "react";
import { cn } from "./cn";

export function Badge({ className, ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("studio-badge", className)} {...rest} />;
}

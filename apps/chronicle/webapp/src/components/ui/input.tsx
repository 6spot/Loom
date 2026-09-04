// shadcn/ui-style Input / Label (Studio only).
import { forwardRef } from "react";
import type { InputHTMLAttributes, LabelHTMLAttributes } from "react";
import { cn } from "./cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={cn("studio-input", className)} {...rest} />;
});

export function Label({ className, ...rest }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("studio-label", className)} {...rest} />;
}

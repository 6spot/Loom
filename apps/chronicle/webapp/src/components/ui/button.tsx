// shadcn/ui-style Button (Studio foundation only; public Chronicle pages
// must not import from components/ui so product styling stays independent).
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "default" | "secondary" | "outline" | "ghost" | "destructive";
type Size = "sm" | "default" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const VARIANTS: Record<Variant, string> = {
  default: "studio-btn-default",
  secondary: "studio-btn-secondary",
  outline: "studio-btn-outline",
  ghost: "studio-btn-ghost",
  destructive: "studio-btn-destructive",
};

const SIZES: Record<Size, string> = {
  sm: "studio-btn-sm",
  default: "studio-btn-md",
  lg: "studio-btn-lg",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "default", className, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} className={cn("studio-btn", VARIANTS[variant], SIZES[size], className)} {...rest} />
  );
});

// Minimal class-name joiner (shadcn `cn` equivalent without extra deps).
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type Tone = "default" | "primary" | "muted" | "success" | "danger" | "outline";

const tones: Record<Tone, string> = {
  default: "bg-secondary text-secondary-foreground",
  primary: "bg-primary/15 text-primary border border-primary/30",
  muted: "bg-muted text-muted-foreground",
  success:
    "bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] border border-[hsl(var(--success)/0.3)]",
  danger: "bg-destructive/15 text-destructive border border-destructive/30",
  outline: "border border-border text-muted-foreground",
};

export function Badge({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Моноширинная плашка-роль (cover / advantages / …) — мотив пайплайна. */
export function RoleTag({ role, className }: { role: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border border-border bg-background/50 px-1.5 py-0.5",
        "font-mono text-[0.66rem] uppercase tracking-[0.12em] text-muted-foreground",
        className,
      )}
    >
      {role}
    </span>
  );
}

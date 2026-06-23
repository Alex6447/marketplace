import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// Поле формы: подпись-«насечка» сверху (моноширинный, разреженный регистр) + контрол.
export function Field({
  label,
  hint,
  htmlFor,
  children,
  className,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="flex items-baseline justify-between font-mono text-[0.68rem] uppercase tracking-[0.16em] text-muted-foreground"
      >
        <span>{label}</span>
        {hint ? <span className="tracking-normal normal-case opacity-70">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}

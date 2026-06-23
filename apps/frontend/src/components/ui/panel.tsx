import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// Базовая «карточка-панель» в стилистике ателье: тёплая подложка, тонкая рамка.
export function Panel({
  children,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag
      className={cn(
        "rounded-lg border border-border bg-card/70 text-card-foreground backdrop-blur-sm",
        "shadow-[0_1px_0_0_hsl(0_0%_100%/0.03)_inset,0_12px_30px_-24px_hsl(0_0%_0%/0.6)]",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

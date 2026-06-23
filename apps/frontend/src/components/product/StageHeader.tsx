import type { ReactNode } from "react";

// Заголовок стадии пайплайна: крупный моноширинный номер в скобках — общий мотив.
export function StageHeader({
  numeral,
  title,
  subtitle,
  action,
}: {
  numeral: string;
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <span className="stage-numeral select-none text-2xl leading-none text-primary">
          [{numeral}]
        </span>
        <div>
          <h3 className="font-display text-xl leading-none">{title}</h3>
          {subtitle ? (
            <p className="mt-2 max-w-md text-sm text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

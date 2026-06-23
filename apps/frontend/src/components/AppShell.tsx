import { useQuery } from "@tanstack/react-query";
import { Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { fetchHealth } from "@/lib/api";
import { href, navigate } from "@/lib/router";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

function ApiDot() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });
  const ok = health.isSuccess;
  const label = health.isLoading ? "связь…" : ok ? "api · online" : "api · offline";
  return (
    <span className="hidden items-center gap-2 font-mono text-[0.66rem] uppercase tracking-[0.14em] text-muted-foreground sm:inline-flex">
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          health.isLoading
            ? "bg-muted-foreground animate-pulse"
            : ok
              ? "bg-[hsl(var(--success))] shadow-[0_0_8px_hsl(var(--success))]"
              : "bg-destructive",
        )}
      />
      {label}
    </span>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
      title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

export interface Crumb {
  label: string;
  to?: import("@/lib/router").Route;
}

export function AppShell({ crumbs, children }: { crumbs: Crumb[]; children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3.5">
          <a
            href={href({ name: "projects" })}
            className="group flex items-center gap-2.5"
            onClick={(e) => {
              e.preventDefault();
              navigate({ name: "projects" });
            }}
          >
            <span className="grid h-7 w-7 place-items-center rounded-[7px] bg-primary font-display text-sm font-bold text-primary-foreground shadow-[0_0_18px_-4px_hsl(var(--primary))]">
              К
            </span>
            <span className="font-display text-[0.95rem] font-semibold tracking-tight">
              Студия<span className="text-primary">·</span>карточек
            </span>
          </a>
          <div className="flex items-center gap-1.5">
            <ApiDot />
            <ThemeToggle />
          </div>
        </div>
        <div className="h-px w-full bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
      </header>

      <main className="mx-auto max-w-6xl px-5 pb-24 pt-7">
        <nav className="mb-7 flex flex-wrap items-center gap-1.5 font-mono text-[0.7rem] text-muted-foreground">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 ? <span className="opacity-40">/</span> : null}
              {c.to && i < crumbs.length - 1 ? (
                <a
                  href={href(c.to)}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(c.to!);
                  }}
                  className="transition-colors hover:text-foreground"
                >
                  {c.label}
                </a>
              ) : (
                <span className={i === crumbs.length - 1 ? "text-foreground" : undefined}>
                  {c.label}
                </span>
              )}
            </span>
          ))}
        </nav>
        {children}
      </main>
    </div>
  );
}

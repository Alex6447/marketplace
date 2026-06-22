import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchHealth } from "@/lib/api";

// Каркас дашборда: проверяет связь с API через TanStack Query. Полноценные экраны
// (создание проекта, загрузка товара, идеи/концепции, версии, фидбэк) — Этапы 1–4.
function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="container mx-auto flex max-w-2xl flex-col gap-6 py-16">
        <header className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">AI Marketplace Cards</h1>
          <p className="text-muted-foreground">
            Каркас дашборда менеджера. Ниже — проверка связи с API.
          </p>
        </header>

        <section className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-1">
              <p className="text-sm font-medium">Статус API</p>
              <ApiStatus
                isLoading={health.isLoading}
                isError={health.isError}
                status={health.data?.status}
              />
            </div>
            <Button
              variant="outline"
              onClick={() => health.refetch()}
              disabled={health.isFetching}
            >
              {health.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Проверить снова
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

function ApiStatus({
  isLoading,
  isError,
  status,
}: {
  isLoading: boolean;
  isError: boolean;
  status?: string;
}) {
  if (isLoading) {
    return (
      <span className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Проверяем…
      </span>
    );
  }
  if (isError) {
    return (
      <span className="flex items-center gap-2 text-destructive">
        <XCircle className="h-4 w-4" /> Нет связи с API
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2 text-emerald-600">
      <CheckCircle2 className="h-4 w-4" /> {status ?? "ok"}
    </span>
  );
}

export default App;

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageOff, ImagePlus, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { RoleTag } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { ErrorRow, LoadingRow, Spinner } from "@/components/ui/states";
import { listAssets, uploadAsset, type ProductAsset } from "@/lib/api";
import { describeError } from "@/views/ProjectsView";
import { cn } from "@/lib/utils";

export function AssetsPanel({ productId }: { productId: string }) {
  const qc = useQueryClient();
  const assets = useQuery({
    queryKey: ["assets", productId],
    queryFn: () => listAssets(productId),
  });
  const [type, setType] = useState<"photo" | "reference">("photo");
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (file: File) => uploadAsset(productId, file, type),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", productId] }),
  });

  return (
    <Panel className="p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-display text-base">Фото и референсы</h3>
        <div className="inline-flex rounded-md border border-border p-0.5 text-xs">
          {(["photo", "reference"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setType(t)}
              className={cn(
                "rounded-[5px] px-2.5 py-1 font-mono uppercase tracking-[0.1em] transition-colors",
                type === t
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t === "photo" ? "фото" : "референс"}
            </button>
          ))}
        </div>
      </div>

      <p className="mb-4 text-sm text-muted-foreground">
        <span className="text-foreground">Фото</span> — исходник товара, который система сохраняет
        без искажений. <span className="text-foreground">Референс</span> — пример сцены или стиля.
      </p>

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = "";
        }}
      />
      <Button
        variant="outline"
        className="w-full border-dashed"
        onClick={() => fileRef.current?.click()}
        disabled={upload.isPending}
      >
        {upload.isPending ? <Spinner /> : <Upload className="h-4 w-4" />}
        Загрузить {type === "photo" ? "фото" : "референс"}
      </Button>

      {upload.isError ? (
        <div className="mt-3">
          <ErrorRow message={describeError(upload.error)} />
        </div>
      ) : null}

      <div className="mt-5">
        {assets.isLoading ? (
          <LoadingRow label="Загрузка файлов…" />
        ) : assets.isError ? (
          <ErrorRow message={describeError(assets.error)} />
        ) : assets.data && assets.data.length > 0 ? (
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4">
            {assets.data.map((a) => (
              <AssetThumb key={a.id} asset={a} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
            <ImagePlus className="h-5 w-5 opacity-60" />
            Файлов пока нет
          </div>
        )}
      </div>
    </Panel>
  );
}

function AssetThumb({ asset }: { asset: ProductAsset }) {
  const [broken, setBroken] = useState(false);
  return (
    <figure className="group relative aspect-square overflow-hidden rounded-md border border-border bg-background/50">
      {asset.url && !broken ? (
        <img
          src={asset.url}
          alt={asset.type}
          loading="lazy"
          onError={() => setBroken(true)}
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-muted-foreground/50">
          <ImageOff className="h-5 w-5" />
        </div>
      )}
      <figcaption className="absolute left-1 top-1">
        <RoleTag role={asset.type === "photo" ? "фото" : "референс"} />
      </figcaption>
    </figure>
  );
}

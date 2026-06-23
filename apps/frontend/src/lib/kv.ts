// Характеристики и требования товара — это произвольные JSON-объекты. В UI их
// удобнее вводить построчно как «ключ: значение». Здесь — разбор и обратная сборка.

export function parseKeyValues(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const sep = line.indexOf(":");
    if (sep === -1) {
      out[line] = "";
    } else {
      const key = line.slice(0, sep).trim();
      const value = line.slice(sep + 1).trim();
      if (key) out[key] = value;
    }
  }
  return out;
}

export function formatKeyValues(obj: Record<string, unknown>): string {
  return Object.entries(obj)
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join("\n");
}

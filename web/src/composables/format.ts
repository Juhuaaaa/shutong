import { t } from "@/i18n";

export function scanSummary(counts: Record<string, number>): string {
  return t("library.scanDone", {
    executed: counts.executed ?? 0,
    review: counts.needs_review ?? 0,
    published: counts.published ?? 0,
  });
}

const UNFINISHED = ["discovered", "parsed", "matched", "planned", "ready", "building"];
const unfinished = (counts: Record<string, number>) => UNFINISHED.reduce((sum, key) => sum + (counts[key] ?? 0), 0);
const failed = (counts: Record<string, number>) => (counts.failed ?? 0) + (counts.cancelled ?? 0);

/** What a drop did, one mention per file: only the parts that happened. */
export function dropSummary(counts: Record<string, number>): string {
  const parts: [string, number][] = [
    ["published", counts.published ?? 0], ["review", counts.needs_review ?? 0], ["unfinished", unfinished(counts)],
    ["failed", failed(counts)], ["duplicate", counts.duplicate ?? 0],
  ];
  const known = counts.known ?? 0;
  if (parts.every(([, value]) => !value)) {
    return known ? t("desktop.drop.done.allKnown", { count: known }) : t("desktop.drop.done.nothing");
  }
  return [...parts, ["known", known] as [string, number]]
    .filter(([, value]) => value).map(([key, value]) => t(`desktop.drop.done.${key}`, { count: value })).join("，");
}

/** Something in the drop still wants the user: not a success to wave through. */
export function dropAttention(counts: Record<string, number>): boolean {
  return unfinished(counts) + failed(counts) > 0;
}

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function humanSize(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return t("time.now");
  if (minutes < 60) return t("time.minutes", { n: minutes });
  if (minutes < 60 * 24) return t("time.hours", { n: Math.floor(minutes / 60) });
  if (minutes < 60 * 24 * 7) return t("time.days", { n: Math.floor(minutes / 60 / 24) });
  return shortTime(iso);
}

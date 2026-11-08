/** One readable line for an item event's detail (the history timeline never shows raw JSON). */
import { t, i18n } from "@/i18n";
import { sourceLabel } from "./volume";

const HIDDEN = new Set(["sha256", "fingerprint", "raw", "request"]);

function label(key: string): string {
  return i18n.global.te(`eventDetail.key.${key}`) ? t(`eventDetail.key.${key}`) : key;
}

function note(text: string): string {
  const key = text.replace(/[^a-z]+/gi, "_").replace(/^_|_$/g, "");
  return i18n.global.te(`eventDetail.note.${key}`) ? t(`eventDetail.note.${key}`) : text;
}

function value(key: string, raw: unknown): string | null {
  if (raw === null || raw === undefined || raw === "") return null;
  if (key === "note" && typeof raw === "string") return note(raw);
  if (key === "confidence" && typeof raw === "number") return raw.toFixed(2);
  if (key === "volume" && typeof raw === "string") return raw.replace(/^volume:/, "").replace(/^chapter:/, "Ch.");
  if (Array.isArray(raw)) return raw.length ? raw.map((entry) => subjectText(entry) ?? (typeof entry === "object" ? "…" : String(entry))).join("、") : null;
  if (typeof raw === "object") return subjectText(raw);
  if (typeof raw === "boolean") return raw ? t("eventDetail.yes") : t("eventDetail.no");
  return String(raw);
}

/** ``{source, id}``: an entry of a metadata source. */
function subjectText(raw: unknown): string | null {
  if (!raw || typeof raw !== "object") return null;
  const { source, id } = raw as { source?: unknown; id?: unknown };
  return typeof source === "string" && (typeof id === "string" || typeof id === "number") ? `${sourceLabel(source)} ${id}` : null;
}

export function eventDetail(detail: Record<string, unknown> | null | undefined): string {
  const parts: string[] = [];
  for (const [key, raw] of Object.entries(detail ?? {})) {
    if (HIDDEN.has(key)) continue;
    const text = value(key, raw);
    if (text === null) continue;
    parts.push(key === "note" ? text : `${label(key)}：${text}`);
  }
  return parts.join("；");
}

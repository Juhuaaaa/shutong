/** Same forms the backend accepts for a typed volume (shutong.engine.overrides.parse_volume_text). */
export function isVolumeText(text: string, kind: "manga" | "novel" = "manga"): boolean {
  const value = text.trim();
  if (/^\d+(\.\d+)?$/.test(value) || /^sp\s*0*\d+$/i.test(value)) return true;
  if (kind === "novel") return false; // a novel has no merged volumes or chapters
  if (/^ch\.?\s*\d+(\.\d+)?$/i.test(value) || /^第?\s*\d+(\.\d+)?\s*[话話]$/.test(value)) return true;
  const range = value.match(/^(\d+)\s*-\s*(\d+)$/);
  return range !== null && Number(range[1]) < Number(range[2]);
}

/** "婚戒物语[东立电子版]" → "东立电子版" */
export function editionOf(folder: string): string | null {
  return folder.match(/\[([^[\]]+)\]\s*$/)?.[1] ?? null;
}

export interface SubjectRef {
  source: string;
  id: string;
}

const LINKS: [RegExp, string][] = [
  [/(?:bgm\.tv|bangumi\.tv|chii\.in)\/subject\/(\d+)/i, "bangumi"],
  [/anilist\.co\/manga\/(\d+)/i, "anilist"],
];

/** A subject from a pasted link (its site names the source) or a typed number (in ``fallbackSource``). */
export function subjectRefOf(text: string, fallbackSource: string): SubjectRef | null {
  const value = text.trim();
  for (const [pattern, source] of LINKS) {
    const match = value.match(pattern);
    if (match) return positive(match[1]) ? { source, id: String(Number(match[1])) } : null;
  }
  return /^\d+$/.test(value) && positive(value) ? { source: fallbackSource, id: String(Number(value)) } : null;
}

function positive(digits: string): boolean {
  const id = Number(digits);
  return Number.isSafeInteger(id) && id > 0;
}

export function sameSubject(a: SubjectRef | null | undefined, b: SubjectRef | null | undefined): boolean {
  return Boolean(a && b && a.source === b.source && a.id === b.id);
}

const SOURCE_LABELS: Record<string, string> = { bangumi: "Bangumi", anilist: "AniList" };

export function sourceLabel(name: string | null | undefined): string {
  return name ? (SOURCE_LABELS[name] ?? name) : "";
}

/** A subject's public page, made from its source and id. */
export function subjectUrl(source: string | null | undefined, id: string | null | undefined): string {
  if (!id) return "";
  if (source === "anilist") return `https://anilist.co/manga/${id}`;
  if (!source || source === "bangumi") return `https://bgm.tv/subject/${id}`;
  return "";
}

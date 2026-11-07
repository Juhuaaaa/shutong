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

/** A Bangumi subject id from a typed number or a pasted link: 439286, https://bgm.tv/subject/439286 */
export function subjectIdOf(text: string): number | null {
  const match = text.trim().match(/^(\d+)$|(?:bgm\.tv|bangumi\.tv|chii\.in)\/subject\/(\d+)/i);
  const id = match ? Number(match[1] ?? match[2]) : 0;
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

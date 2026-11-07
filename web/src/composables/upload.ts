/** Drag-and-drop uploads: walk dropped folders, then send one request per file, a few at a time. */
import type { UploadResult } from "@/api";

export interface PendingFile {
  path: string; // relative path, e.g. "迷宫饭/Vol.01.zip"
  file: File;
}

export interface UploadSummary {
  saved: number;
  skipped: number;
  failed: { path: string; error: string }[];
}

interface Entry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (ok: (file: File) => void, fail?: (error: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (entries: Entry[]) => void, fail?: (error: unknown) => void) => void };
}

async function walk(entry: Entry, prefix: string, out: PendingFile[]): Promise<void> {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile && entry.file) {
    out.push({ path, file: await new Promise<File>((ok, fail) => entry.file!(ok, fail)) });
    return;
  }
  if (!entry.isDirectory || !entry.createReader) return;
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise<Entry[]>((ok, fail) => reader.readEntries(ok, fail));
    if (!batch.length) return;
    for (const child of batch) await walk(child, path, out);
  }
}

export async function collectEntries(entries: Entry[]): Promise<PendingFile[]> {
  const out: PendingFile[] = [];
  for (const entry of entries) await walk(entry, "", out);
  return out;
}

export async function filesFromDrop(transfer: DataTransfer): Promise<PendingFile[]> {
  const entries = [...transfer.items]
    .map((item) => (item.webkitGetAsEntry ? (item.webkitGetAsEntry() as unknown as Entry | null) : null))
    .filter((entry): entry is Entry => entry !== null);
  if (entries.length) return collectEntries(entries);
  return [...transfer.files].map((file) => ({ path: file.name, file }));
}

export function filesFromInput(list: FileList): PendingFile[] {
  return [...list].map((file) => ({ path: file.webkitRelativePath || file.name, file }));
}

export async function uploadAll(
  files: PendingFile[],
  send: (file: PendingFile) => Promise<UploadResult>,
  onProgress: (done: number, total: number) => void = () => {},
  concurrency = 3,
): Promise<UploadSummary> {
  const summary: UploadSummary = { saved: 0, skipped: 0, failed: [] };
  let next = 0;
  let done = 0;
  async function worker() {
    while (next < files.length) {
      const file = files[next++];
      try {
        const result = await send(file);
        summary.saved += result.saved.length;
        summary.skipped += result.skipped.length;
      } catch (error) {
        summary.failed.push({ path: file.path, error: (error as Error).message });
      }
      onProgress(++done, files.length);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, files.length) }, worker));
  return summary;
}

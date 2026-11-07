/** Moving dropped originals to the system trash. The page only names item ids: the paths come from the backend,
 * so the page can never have anything else moved. */
export interface Original {
  id: number;
  path: string;
}

export function selectTrashable(requested: number[], originals: Original[]): Original[] {
  const wanted = new Set(requested);
  return originals.filter((item) => wanted.has(item.id));
}

export interface TrashDeps {
  originals(): Promise<Original[]>;
  trash(path: string): Promise<void>;
  /** Tells the backend; answers which folders hold nothing but junk now. */
  trashed(ids: number[]): Promise<string[]>;
}

export interface TrashResult {
  trashed: number[];
  failed: { id: number; error: string }[];
}

export async function trashOriginals(requested: number[], deps: TrashDeps): Promise<TrashResult> {
  const result: TrashResult = { trashed: [], failed: [] };
  for (const item of selectTrashable(requested, await deps.originals())) {
    try {
      await deps.trash(item.path);
      result.trashed.push(item.id);
    } catch (error) {
      result.failed.push({ id: item.id, error: `${item.path.split(/[/\\]/).pop()}：${(error as Error).message}` });
    }
  }
  if (result.trashed.length) {
    for (const folder of await deps.trashed(result.trashed)) {
      await deps.trash(folder).catch(() => {}); // the files are gone; an empty folder left behind is harmless
    }
  }
  return result;
}

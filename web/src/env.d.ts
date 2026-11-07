declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

/** What the desktop app's window can ask of the system. Absent in a plain browser. */
interface ShutongBridge {
  pathsFor(files: File[]): string[];
  pickFolder(defaultPath?: string): Promise<string | null>;
  openPath(path: string): Promise<void>;
  defaultLibraryDir(kind: "manga" | "novel"): Promise<string>;
  trashOriginals(ids: number[]): Promise<{ trashed: number[]; failed: { id: number; error: string }[] }>;
  onUpdate(callback: (info: { version: string; url: string }) => void): void;
  openExternal(url: string): void;
}

interface Window {
  shutong?: ShutongBridge;
}

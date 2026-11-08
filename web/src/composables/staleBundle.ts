/**
 * After an upgrade the page's bundles have new names: a page still open (or cached) asks for the old ones and they
 * are gone. Vite reports that as ``vite:preloadError``; loading the page again picks up the new build. Only once a
 * minute, so a real network problem shows its error instead of reloading forever.
 */
const KEY = "shutong.staleReloadAt";

interface Store { getItem(key: string): string | null; setItem(key: string, value: string): void }

export function reloadOnStaleBundle(target: EventTarget, reload: () => void, storage: Store | null,
  now: () => number = Date.now): void {
  target.addEventListener("vite:preloadError", (event) => {
    let last: number;
    try {
      last = Number(storage?.getItem(KEY) ?? 0);
    } catch {
      last = 0;
    }
    if (now() - last < 60_000) return;
    try {
      storage?.setItem(KEY, String(now()));
    } catch {
      // without storage it still reloads; the browser's own error shows if it fails again
    }
    event.preventDefault();
    reload();
  });
}

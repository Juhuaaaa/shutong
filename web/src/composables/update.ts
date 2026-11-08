/**
 * Is there a newer Shutong? The desktop app asks GitHub itself and tells the page; a server's page (Docker) asks
 * from the browser, at most once a day. Nothing is sent but the request, and a failed check bothers nobody.
 */
const RELEASES_API = "https://api.github.com/repos/Juhuaaaa/shutong/releases/latest";
const KEY = "shutong.latestRelease";
const DAY_MS = 24 * 3600 * 1000;

export interface Release { version: string; url: string }
interface Store { getItem(key: string): string | null; setItem(key: string, value: string): void }

function parts(version: string): number[] | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(version.trim());
  return match ? match.slice(1).map(Number) : null;
}

export function isNewer(latest: string, current: string): boolean {
  const a = parts(latest);
  const b = parts(current);
  if (!a || !b) return false;
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] > b[index];
  }
  return false;
}

function remembered(storage: Store | null, now: number): Release | null | undefined {
  try {
    const saved = JSON.parse(storage?.getItem(KEY) ?? "null") as { at: number; release: Release | null } | null;
    if (saved && typeof saved.at === "number" && now >= saved.at && now - saved.at < DAY_MS) return saved.release;
  } catch {
    // a broken entry is asked again
  }
  return undefined;
}

/** ``desktop-v1.2.3`` or ``v1.2.3`` on github.com; anything else is no release. */
export async function latestRelease(fetcher: typeof fetch, storage: Store | null, now: number = Date.now()): Promise<Release | null> {
  const known = remembered(storage, now);
  if (known !== undefined) return known;
  let release: Release | null = null;
  try {
    const response = await fetcher(RELEASES_API, { headers: { Accept: "application/vnd.github+json" } });
    if (response.ok) {
      const body = (await response.json()) as { tag_name?: unknown; html_url?: unknown };
      const version = typeof body.tag_name === "string" ? body.tag_name.replace(/^desktop-/, "").replace(/^v/, "") : "";
      if (parts(version) && typeof body.html_url === "string" && body.html_url.startsWith("https://github.com/")) {
        release = { version, url: body.html_url };
      }
    }
  } catch {
    return null;  // offline: try again next time
  }
  try {
    storage?.setItem(KEY, JSON.stringify({ at: now, release }));
  } catch {
    // without storage it simply asks again next time
  }
  return release;
}

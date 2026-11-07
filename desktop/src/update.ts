/** Tell about a new version, once a day at most; a failed check bothers nobody. Nothing is sent but the request. */
export const RELEASES_API = "https://api.github.com/repos/Juhuaaaa/shutong/releases/latest";
const DAY_MS = 24 * 3600 * 1000;
const TIMEOUT_MS = 5_000;

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

export function shouldCheck(lastChecked: number | undefined, now: number): boolean {
  return lastChecked === undefined || now < lastChecked || now - lastChecked >= DAY_MS;
}

export interface Update {
  version: string;
  url: string;
}

/** The tag is ``desktop-v1.2.3`` or ``v1.2.3``. */
export async function latestRelease(fetcher: typeof fetch): Promise<Update | null> {
  try {
    const response = await fetcher(RELEASES_API, {
      headers: { Accept: "application/vnd.github+json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return null;
    const release = (await response.json()) as { tag_name?: unknown; html_url?: unknown; draft?: unknown; prerelease?: unknown };
    if (release.draft || release.prerelease || typeof release.tag_name !== "string" || typeof release.html_url !== "string") return null;
    const version = release.tag_name.replace(/^desktop-/, "").replace(/^v/, "");
    return parts(version) && release.html_url.startsWith("https://github.com/") ? { version, url: release.html_url } : null;
  } catch {
    return null;
  }
}

import { describe, expect, it, vi } from "vitest";
import { isNewer, latestRelease } from "./update";

function memory() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => void values.set(key, value) };
}

function answer(body: object, ok = true) {
  return vi.fn(async () => ({ ok, json: async () => body }) as Response);
}

describe("isNewer", () => {
  it("compares versions number by number", () => {
    expect(isNewer("0.2.10", "0.2.9")).toBe(true);
    expect(isNewer("0.2.1", "0.2.1")).toBe(false);
    expect(isNewer("0.1.9", "0.2.0")).toBe(false);
    expect(isNewer("latest", "0.2.0")).toBe(false);
  });
});

describe("latestRelease", () => {
  const release = { tag_name: "desktop-v0.3.0", html_url: "https://github.com/Juhuaaaa/shutong/releases/tag/desktop-v0.3.0" };

  it("reads the latest release, and asks GitHub at most once a day", async () => {
    const storage = memory();
    const fetcher = answer(release);
    const now = 1_800_000_000_000;
    expect(await latestRelease(fetcher, storage, now)).toEqual({ version: "0.3.0", url: release.html_url });
    expect(await latestRelease(fetcher, storage, now + 3600_000)).toEqual({ version: "0.3.0", url: release.html_url });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await latestRelease(fetcher, storage, now + 25 * 3600_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("gives nothing for a failed check or an odd answer", async () => {
    expect(await latestRelease(answer({}, false), memory(), 1)).toBeNull();
    expect(await latestRelease(answer({ tag_name: "nightly", html_url: release.html_url }), memory(), 1)).toBeNull();
    expect(await latestRelease(answer({ ...release, html_url: "https://evil.example/x" }), memory(), 1)).toBeNull();
    expect(await latestRelease(vi.fn(async () => { throw new Error("offline"); }), memory(), 1)).toBeNull();
  });
});

import { describe, expect, it, vi } from "vitest";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { parseReadyLine, startBackend } from "./backend";
import { externalAllowed, isAllowedNavigation } from "./navigation";
import { selectTrashable, trashOriginals } from "./originals";
import { cacheIsStale } from "./state";
import { isNewer, latestRelease, shouldCheck } from "./update";

describe("cacheIsStale", () => {
  it("drops the page cache once after every upgrade, and from versions that did not remember theirs", () => {
    expect(cacheIsStale({}, "0.2.1")).toBe(true);
    expect(cacheIsStale({ appVersion: "0.2.0" }, "0.2.1")).toBe(true);
    expect(cacheIsStale({ appVersion: "0.2.1" }, "0.2.1")).toBe(false);
  });
});

describe("parseReadyLine", () => {
  it("reads the port", () => expect(parseReadyLine('SHUTONG_READY {"port": 43210}')).toEqual({ port: 43210 }));
  it("reads a refusal", () => expect(parseReadyLine('SHUTONG_ERROR {"code": "schema_too_new", "message": "太新"}'))
    .toEqual({ error: "schema_too_new", message: "太新" }));
  it("ignores anything else", () => {
    for (const line of ["", "INFO started", "SHUTONG_READY {broken", 'SHUTONG_READY {"port": 0}', 'SHUTONG_READY {"port": "80"}', 'x SHUTONG_READY {"port": 1}']) {
      expect(parseReadyLine(line)).toBeNull();
    }
  });
});

describe("startBackend", () => {
  it("keeps what a crash before logging starts says", async () => {
    const stderrFile = path.join(mkdtempSync(path.join(tmpdir(), "shutong-")), "logs", "backend-stderr.log");
    await expect(startBackend({ command: process.execPath, args: ["-e", "console.error('迁移失败'); process.exit(1)"], env: {}, stderrFile }))
      .rejects.toThrow("退出码 1");
    expect(readFileSync(stderrFile, "utf8")).toContain("迁移失败");
  });
});

describe("navigation", () => {
  it("keeps the window on our own address", () => {
    expect(isAllowedNavigation("http://127.0.0.1:8123/review", 8123)).toBe(true);
    for (const url of ["http://127.0.0.1:9999/", "https://127.0.0.1:8123/", "http://evil.example/", "http://127.0.0.1.evil.example:8123/",
      "http://127.0.0.1:8123@evil.example/", "file:///etc/passwd", "javascript:alert(1)", "not a url"]) {
      expect(isAllowedNavigation(url, 8123)).toBe(false);
    }
  });
  it("hands only web links to the system", () => {
    expect(externalAllowed("https://bgm.tv/subject/1")).toBe(true);
    for (const url of ["file:///etc/passwd", "javascript:alert(1)", "smb://x/y", "x"]) expect(externalAllowed(url)).toBe(false);
  });
});

describe("update check", () => {
  it("compares versions as numbers", () => {
    expect(isNewer("0.10.0", "0.9.9")).toBe(true);
    expect(isNewer("v1.0.0", "0.9.9")).toBe(true);
    expect(isNewer("0.1.0", "0.1.0")).toBe(false);
    expect(isNewer("0.0.9", "0.1.0")).toBe(false);
  });
  it("does not trust a malformed version", () => {
    for (const version of ["latest", "1.2", "1.2.3-beta", ""]) expect(isNewer(version, "0.1.0")).toBe(false);
  });
  it("checks once a day", () => {
    const day = 24 * 3600 * 1000;
    expect(shouldCheck(undefined, 1000)).toBe(true);
    expect(shouldCheck(0, day - 1)).toBe(false);
    expect(shouldCheck(0, day)).toBe(true);
    expect(shouldCheck(5000, 1000)).toBe(true); // the clock went back
  });
  const answer = (body: unknown, ok = true) => vi.fn(async () => new Response(JSON.stringify(body), { status: ok ? 200 : 403 })) as unknown as typeof fetch;
  it("reads the release", async () => {
    expect(await latestRelease(answer({ tag_name: "desktop-v0.2.0", html_url: "https://github.com/a/b/releases/1" })))
      .toEqual({ version: "0.2.0", url: "https://github.com/a/b/releases/1" });
  });
  it("stays silent on anything unexpected", async () => {
    const rejected = vi.fn(async () => { throw new Error("offline"); }) as unknown as typeof fetch;
    expect(await latestRelease(rejected)).toBeNull();
    expect(await latestRelease(answer({}, false))).toBeNull();
    expect(await latestRelease(answer({ tag_name: "v1.0.0" }))).toBeNull();
    expect(await latestRelease(answer({ tag_name: "v1.0.0", html_url: "https://evil.example/x" }))).toBeNull();
    expect(await latestRelease(answer({ tag_name: "v1.0.0", html_url: "https://github.com/x", prerelease: true }))).toBeNull();
  });
});

describe("trashing originals", () => {
  const originals = [{ id: 1, path: "/下载/a.zip" }, { id: 2, path: "/下载/b.zip" }];
  it("ignores ids the backend does not offer", () => {
    expect(selectTrashable([2, 99], originals)).toEqual([originals[1]]);
  });
  it("never touches a path the backend did not name", async () => {
    const trash = vi.fn(async () => {});
    const trashed = vi.fn(async () => []);
    const result = await trashOriginals([99], { originals: async () => originals, trash, trashed });
    expect(trash).not.toHaveBeenCalled();
    expect(trashed).not.toHaveBeenCalled();
    expect(result).toEqual({ trashed: [], failed: [] });
  });
  it("carries on past a locked file, then clears the folders left empty", async () => {
    const trash = vi.fn(async (target: string) => {
      if (target === "/下载/a.zip") throw new Error("被占用");
    });
    const trashed = vi.fn(async () => ["/下载/空的"]);
    const result = await trashOriginals([1, 2], { originals: async () => originals, trash, trashed });
    expect(result).toEqual({ trashed: [2], failed: [{ id: 1, error: "a.zip：被占用" }] });
    expect(trashed).toHaveBeenCalledWith([2]);
    expect(trash).toHaveBeenCalledWith("/下载/空的");
  });
});

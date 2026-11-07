import { describe, expect, it } from "vitest";
import { collectEntries, uploadAll, type PendingFile } from "./upload";

function fileEntry(name: string) {
  return { isFile: true, isDirectory: false, name, file: (ok: (file: File) => void) => ok(new File(["x"], name)) };
}

function dirEntry(name: string, children: unknown[]) {
  let read = false;
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => ({
      // Browsers hand out directory entries in batches until an empty batch.
      readEntries: (ok: (entries: unknown[]) => void) => {
        ok(read ? [] : children);
        read = true;
      },
    }),
  };
}

describe("collectEntries", () => {
  it("walks dropped folders and keeps relative paths", async () => {
    const dropped = [dirEntry("迷宫饭", [fileEntry("Vol.01.zip"), dirEntry("番外", [fileEntry("SP1.zip")])]), fileEntry("x.zip")];
    const files = await collectEntries(dropped as never);
    expect(files.map((file) => file.path)).toEqual(["迷宫饭/Vol.01.zip", "迷宫饭/番外/SP1.zip", "x.zip"]);
  });
});

describe("uploadAll", () => {
  it("sends one request per file, at most three at a time", async () => {
    const files: PendingFile[] = Array.from({ length: 7 }, (_, index) => ({ path: `a/${index}.zip`, file: new File(["x"], `${index}.zip`) }));
    let active = 0;
    let peak = 0;
    const seen: string[] = [];
    const progress: number[] = [];
    const result = await uploadAll(files, async (file) => {
      active += 1;
      peak = Math.max(peak, active);
      seen.push(file.path);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return file.path.endsWith("3.zip") ? { saved: [], skipped: [file.path] } : { saved: [{ name: file.path, path: file.path }], skipped: [] };
    }, (done) => progress.push(done));
    expect(seen.sort()).toEqual(files.map((file) => file.path).sort());
    expect(peak).toBeLessThanOrEqual(3);
    expect([result.saved, result.skipped, result.failed.length]).toEqual([6, 1, 0]);
    expect(progress.at(-1)).toBe(7);
  });

  it("keeps going after one file fails and reports it", async () => {
    const files: PendingFile[] = [{ path: "a.zip", file: new File(["x"], "a.zip") }, { path: "b.zip", file: new File(["x"], "b.zip") }];
    const result = await uploadAll(files, async (file) => {
      if (file.path === "a.zip") throw new Error("不允许的文件路径");
      return { saved: [{ name: file.path, path: file.path }], skipped: [] };
    });
    expect(result.saved).toBe(1);
    expect(result.failed).toEqual([{ path: "a.zip", error: "不允许的文件路径" }]);
  });
});

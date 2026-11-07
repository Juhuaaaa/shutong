import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { fakeApi } from "@/test-utils";
import LogsView from "./LogsView.vue";

function entry(seq: number, level: string, message: string) {
  return { seq, at: "2026-10-30T21:40:01+08:00", level, logger: "shutong.jobs", message };
}

describe("LogsView", () => {
  it("does not lose a filter change made while a request is on its way", async () => {
    const lines = [entry(1, "INFO", "开始任务：扫描 #1"), entry(2, "ERROR", "失败：迷宫饭 Vol.01.zip")];
    let release: (() => void) | null = null;
    fakeApi({
      "GET /api/libraries": [],
      "GET /api/settings": { "log.level": "INFO" },
      "GET /api/logs": async (_: unknown, url: URL) => {
        const level = url.searchParams.get("level");
        if (!level) await new Promise<void>((resolve) => (release = resolve)); // the unfiltered request is slow
        const found = lines.filter((line) => !level || line.level === level);
        return { entries: found, last_seq: 2 };
      },
    });
    const { wrapper } = await mountView(LogsView, "/logs");
    await vi.waitFor(() => expect(release).not.toBeNull());
    await wrapper.find("[data-test=level-ERROR]").trigger("click");
    release!();
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=log-line]").length).toBe(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(wrapper.findAll("[data-test=log-line]").map((line) => line.text())).toEqual([expect.stringContaining("失败")]);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the newest lines, follows new ones and filters by level", async () => {
    let batch = [entry(1, "INFO", "开始任务：扫描 #1"), entry(2, "ERROR", "失败：迷宫饭 Vol.01.zip")];
    const levels: (string | null)[] = [];
    fakeApi({
      "GET /api/libraries": [],
      "GET /api/settings": { "log.level": "INFO" },
      "GET /api/logs": (_: unknown, url: URL) => {
        const after = Number(url.searchParams.get("after") ?? 0);
        levels.push(url.searchParams.get("level"));
        const level = url.searchParams.get("level");
        const found = batch.filter((line) => line.seq > after && (!level || line.level === level));
        return { entries: found, last_seq: Math.max(after, ...batch.map((line) => line.seq)) };
      },
    });
    const { wrapper } = await mountView(LogsView, "/logs");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=log-line]").length).toBe(2));
    expect(wrapper.findAll("[data-test=log-line]")[1].classes()).toContain("level-error");
    batch = [...batch, entry(3, "WARNING", "Bangumi 请求失败（第 1/3 次）")];
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=log-line]").length).toBe(3), { timeout: 4000 });
    await wrapper.find("[data-test=level-ERROR]").trigger("click");
    await vi.waitFor(() => expect(levels).toContain("ERROR"));
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=log-line]").length).toBe(1));
    expect(wrapper.find("[data-test=download]").attributes("href")).toBe("/api/logs/download");
  });
});

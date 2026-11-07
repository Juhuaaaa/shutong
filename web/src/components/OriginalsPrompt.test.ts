import { afterEach, describe, expect, it, vi } from "vitest";
import { notifyState } from "@/composables/notify";
import { mountView } from "@/test-mount";
import { fakeApi, flush } from "@/test-utils";
import OriginalsPrompt from "./OriginalsPrompt.vue";

const ORIGINALS = { items: [{ id: 7, library_id: 1, path: "/下载/a.zip", name: "a.zip" }, { id: 8, library_id: 1, path: "/下载/b.zip", name: "b.zip" }] };

async function open(routes: Record<string, unknown>) {
  const api = fakeApi(routes);
  const mounted = await mountView(OriginalsPrompt, "/");
  await flush();
  return { api, ...mounted };
}

describe("OriginalsPrompt", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says nothing when there is nothing to clean up", async () => {
    const { wrapper } = await open({ "GET /api/desktop/originals": { items: [] } });
    expect(wrapper.find("[data-test=originals-prompt]").exists()).toBe(false);
  });

  it("counts the originals and can leave them for good", async () => {
    const { api, wrapper } = await open({ "GET /api/desktop/originals": ORIGINALS, "POST /api/desktop/originals/keep": { ok: true } });
    expect(wrapper.find("[data-test=originals-prompt]").text()).toContain("已整理 2 个文件");
    await wrapper.find("[data-test=originals-keep]").trigger("click");
    await flush();
    expect(api.calls.at(-1)?.body).toEqual({ ids: [7, 8] });
    expect(wrapper.find("[data-test=originals-prompt]").exists()).toBe(false);
  });

  it("moves them to the trash through the window, and names what failed", async () => {
    // structuredClone: what crossing to the main process does, and a reactive array cannot survive.
    const trashOriginals = vi.fn(async (ids: number[]) => {
      structuredClone(ids);
      return { trashed: [7], failed: [{ id: 8, error: "文件被占用" }] };
    });
    vi.stubGlobal("shutong", { trashOriginals });
    let left = ORIGINALS;
    const { wrapper } = await open({ "GET /api/desktop/originals": () => left });
    left = { items: [ORIGINALS.items[1]] };
    await wrapper.find("[data-test=originals-trash]").trigger("click");
    await flush();
    await flush();
    expect(trashOriginals).toHaveBeenCalledWith([7, 8]);
    expect(notifyState.queue.map((entry) => entry.text).join()).toContain("文件被占用");
    expect(wrapper.find("[data-test=originals-prompt]").text()).toContain("已整理 1 个文件");
  });
});

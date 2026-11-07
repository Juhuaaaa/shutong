import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, flush } from "@/test-utils";
import { mountWith } from "@/test-mount";
import { notify } from "@/composables/notify";
import CoverWallDialog from "./CoverWallDialog.vue";

function item(id: number, status = "published") {
  return { id, library_id: 1, status, source_name: `${id}.zip`, target_path: `迷宫饭/迷宫饭 Vol.0${id}.cbz`, updated_at: "2026-11-06T00:00:00+00:00", plan: {}, parsed: {}, overrides: {} };
}

const LIBRARIES = { "GET /api/libraries": [{ id: 1, name: "漫画", kind: "manga" }], "GET /api/libraries/1/summary": { counts: {} } };

function wall(extra: Record<string, unknown> = {}, props: Record<string, unknown> = {}) {
  const api = fakeApi({ ...LIBRARIES, ...extra });
  return { ...api, wrapper: mountWith(CoverWallDialog, { items: [item(1), item(2), item(3, "failed")], title: "迷宫饭", ...props }) };
}

const q = (selector: string) => document.querySelector(selector) as HTMLElement | null;
const all = (selector: string) => [...document.querySelectorAll(selector)] as HTMLElement[];

vi.mock("@/composables/notify", () => ({ notify: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }));

describe("CoverWallDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("shows each organized volume's cover on one screen", async () => {
    wall();
    await flush();
    const volumes = all("[data-test=wall-volume]");
    expect(volumes.length).toBe(2);
    expect(volumes[0].textContent).toContain("迷宫饭 Vol.01");
    expect(volumes[0].querySelector("img")!.getAttribute("src")).toContain("/api/items/1/cover-image?w=240");
  });

  it("crops the jackets of the shown volumes and says how it went", async () => {
    const { calls } = wall({
      "POST /api/items/crop-jackets": { job_id: 4 },
      "GET /api/jobs/4": { id: 4, kind: "cover", state: "done", result: { cropped: 1, skipped: 1, failed: 0 } },
    });
    await flush();
    q("[data-test=crop-jackets]")!.click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/crop-jackets")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/crop-jackets")?.body).toEqual({ item_ids: [1, 2] });
    await vi.waitFor(() => expect(notify.success).toHaveBeenCalledWith("裁好了 1 卷，跳过 1 卷"));
  });

  async function openPicker(options: unknown, extra: Record<string, unknown> = {}) {
    const api = wall({
      "GET /api/items/1/cover-options": options,
      "POST /api/items/1/cover": { job_id: 5 },
      "GET /api/jobs/5": { id: 5, kind: "cover", state: "done", result: {} },
      ...extra,
    });
    await flush();
    all("[data-test=wall-volume]")[0].click();
    await vi.waitFor(() => expect(q("[data-test=cover-picker]")).not.toBeNull());
    await vi.waitFor(() => expect(q("[data-test=cover-use]")?.hasAttribute("disabled")).toBe(false));
    return api;
  }

  it("uses the page you click", async () => {
    const { calls } = await openPicker({ pages: ["001.jpg", "002.jpg"], current: "001.jpg", added: false, jacket: null });
    all("[data-test=cover-page]")[1].click();
    await flush();
    q("[data-test=cover-use]")!.click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/1/cover")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/1/cover")?.body).toEqual({ page: "002.jpg" });
    await vi.waitFor(() => expect(q("[data-test=cover-picker]")).toBeNull());
  });

  it("frames the front of a jacket it found and crops to that", async () => {
    const { calls } = await openPicker({ pages: ["001.jpg", "002.jpg"], current: "001.jpg", added: false,
      jacket: { page: "001.jpg", left: 0.2, right: 0.55 } });
    expect(q("[data-test=jacket-found]")).not.toBeNull();
    q("[data-test=cover-use]")!.click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/1/cover")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/1/cover")?.body).toEqual({ page: "001.jpg", left: 0.2, right: 0.55 });
  });

  it("goes back to the original cover", async () => {
    const { calls } = await openPicker({ pages: ["001.jpg", "002.jpg"], current: null, added: true, jacket: null });
    q("[data-test=cover-restore]")!.click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/1/cover")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/1/cover")?.body).toEqual({ page: "001.jpg" });
  });
});

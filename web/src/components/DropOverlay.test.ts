import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { mountView } from "@/test-mount";
import { fakeApi, FakeSocket, flush, status } from "@/test-utils";
import { useLibraries } from "@/stores/libraries";
import DropOverlay from "./DropOverlay.vue";

const LIBRARIES = [{ id: 1, name: "漫画库", kind: "manga" }, { id: 2, name: "轻小说库", kind: "novel" }];

function drag(type: string, files: unknown[] = []) {
  const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  Object.defineProperty(event, "dataTransfer", { value: { types: ["Files"], files } });
  return event;
}

async function open(routes: Record<string, unknown> = {}) {
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("shutong", { pathsFor: vi.fn(() => ["/下载/迷宫饭"]) });
  const api = fakeApi(routes);
  const mounted = await mountView(DropOverlay, "/");
  const libraries = useLibraries();
  libraries.list = LIBRARIES as never;
  window.dispatchEvent(drag("dragenter"));
  await nextTick();
  return { api, ...mounted };
}

describe("DropOverlay", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("appears only for a drag carrying files, with one target per library", async () => {
    const { wrapper } = await open();
    expect(wrapper.find("[data-test=drop-1]").text()).toContain("漫画库");
    expect(wrapper.find("[data-test=drop-2]").text()).toContain("轻小说库");
    wrapper.unmount();
  });

  it("stays away for a drag of plain text", async () => {
    fakeApi({});
    const { wrapper } = await mountView(DropOverlay, "/");
    const event = new Event("dragenter", { cancelable: true }) as DragEvent;
    Object.defineProperty(event, "dataTransfer", { value: { types: ["text/plain"] } });
    window.dispatchEvent(event);
    await nextTick();
    expect(wrapper.find("[data-test=drop-overlay]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("sends the real paths to the library they were dropped on", async () => {
    const { api, wrapper } = await open({
      "POST /api/libraries/1/scan-paths": { job_id: null, skipped: [{ path: "/下载/说明.txt", reason: "unsupported" }], rejected: [] },
    });
    await wrapper.find("[data-test=drop-1]").element.dispatchEvent(drag("drop", [{}]));
    await flush();
    expect(api.calls.find((call) => call.method === "POST")?.body).toEqual({ paths: ["/下载/迷宫饭"] });
    expect(document.body.textContent).toContain("说明.txt");
    expect(wrapper.find("[data-test=drop-overlay]").exists()).toBe(false);
    wrapper.unmount();
  });

  it("says the dropped files were handled before", async () => {
    const finished = { id: 7, state: "done", result: { counts: { known: 2, executed: 0, planned: 0 } } };
    const { wrapper } = await open({
      "POST /api/libraries/1/scan-paths": { job_id: 7, skipped: [], rejected: [] },
      "GET /api/jobs/7": finished,
    });
    await wrapper.find("[data-test=drop-1]").element.dispatchEvent(drag("drop", [{}]));
    await vi.waitFor(() => expect(document.body.textContent).toContain("这些文件之前已经处理过（2 个）"), { timeout: 3000 });
    wrapper.unmount();
  });

  it("goes to the AI settings when AI is missing", async () => {
    const { wrapper, router } = await open({ "POST /api/libraries/2/scan-paths": status(409, "请先配置") });
    await wrapper.find("[data-test=drop-2]").element.dispatchEvent(drag("drop", [{}]));
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe("/settings/ai"));
    wrapper.unmount();
  });

  it("does not let the window open a file dropped next to the targets", async () => {
    const { wrapper } = await open();
    const event = drag("drop", [{}]);
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await nextTick();
    expect(wrapper.find("[data-test=drop-overlay]").exists()).toBe(false);
    wrapper.unmount();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { FakeSocket, fakeApi } from "@/test-utils";
import { RouterView } from "vue-router";

function api() {
  return fakeApi({
    "GET /api/libraries": [{ id: 1, name: "漫画", kind: "manga" }],
    "GET /api/libraries/1/summary": { counts: { planned: 12, needs_review: 3 } },
    "GET /api/logs": { entries: [], last_seq: 0 },
    "GET /api/dashboard": { libraries: [], recent: [], jobs: [], storage: [] },
  });
}

function setWidth(width: number) {
  (window as unknown as { happyDOM: { setViewport(size: { width: number; height: number }): void } })
    .happyDOM.setViewport({ width, height: 900 });
}

describe("AppLayout", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("groups the menu and shows waiting counts", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    setWidth(1440);
    api();
    const { wrapper } = await mountView(RouterView, "/logs");
    await vi.waitFor(() => expect(wrapper.find("[data-test=badge-review]").exists()).toBe(true));
    const headings = wrapper.findAll("[data-test=nav-group]").map((node) => node.text());
    expect(headings).toEqual(["概览", "整理", "配置", "系统"]);
    expect(wrapper.find("[data-test=nav-preview]").exists()).toBe(false);
    expect(wrapper.find("[data-test=nav-rules]").exists()).toBe(false);
    expect(wrapper.find("[data-test=badge-review]").text()).toBe("3");
    expect(wrapper.find("[data-test=nav-drawer]").classes()).not.toContain("v-navigation-drawer--temporary");
    expect(wrapper.find("[data-test=nav-dashboard]").classes()).not.toContain("v-list-item--active");
    expect(wrapper.find("[data-test=nav-logs]").classes()).toContain("v-list-item--active");
  });

  it("uses a temporary drawer on narrow screens", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    setWidth(390);
    api();
    const { wrapper } = await mountView(RouterView, "/logs");
    await vi.waitFor(() => expect(wrapper.find("[data-test=nav-drawer]").exists()).toBe(true));
    expect(wrapper.find("[data-test=nav-drawer]").classes()).toContain("v-navigation-drawer--temporary");
  });
});

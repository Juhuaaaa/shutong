import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { FakeSocket, fakeApi } from "@/test-utils";
import { RouterView } from "vue-router";
import { useAuth } from "@/stores/auth";

function api(extra: Record<string, unknown> = {}) {
  return fakeApi({
    ...extra,
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

  it("shows the version at the foot of the menu, and a newer one when there is", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    setWidth(1440);
    localStorage.clear();
    api({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: false, version: "0.2.1" },
      "GET /repos/Juhuaaaa/shutong/releases/latest": {
        tag_name: "desktop-v0.3.0", html_url: "https://github.com/Juhuaaaa/shutong/releases/tag/desktop-v0.3.0" } });
    const { wrapper, pinia } = await mountView(RouterView, "/logs");
    await useAuth(pinia).refresh();
    await vi.waitFor(() => expect(wrapper.find("[data-test=app-version]").text()).toBe("版本 0.2.1"));
    await vi.waitFor(() => expect(wrapper.find("[data-test=app-update]").exists()).toBe(true));
    expect(wrapper.find("[data-test=app-update]").text()).toContain("新版本 0.3.0");
    expect(wrapper.find("[data-test=app-update]").attributes("href")).toBe("https://github.com/Juhuaaaa/shutong/releases/tag/desktop-v0.3.0");
  });

  it("in the desktop app, hears of the update from the app and opens it in the browser", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    setWidth(1440);
    const openExternal = vi.fn();
    vi.stubGlobal("shutong", { openExternal, onUpdate: (callback: (info: { version: string; url: string }) => void) =>
      callback({ version: "0.3.0", url: "https://github.com/Juhuaaaa/shutong/releases/tag/desktop-v0.3.0" }) });
    const { calls } = api({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: true, version: "0.2.1" } });
    const { wrapper, pinia } = await mountView(RouterView, "/logs");
    await useAuth(pinia).refresh();
    await vi.waitFor(() => expect(wrapper.find("[data-test=app-update]").exists()).toBe(true));
    await wrapper.find("[data-test=app-update]").trigger("click");
    expect(openExternal).toHaveBeenCalledWith("https://github.com/Juhuaaaa/shutong/releases/tag/desktop-v0.3.0");
    expect(calls.some((call) => call.path.includes("/releases/latest"))).toBe(false);
  });

  it("says nothing more when this is the newest version", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    setWidth(1440);
    localStorage.clear();
    api({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: false, version: "0.3.0" },
      "GET /repos/Juhuaaaa/shutong/releases/latest": {
        tag_name: "desktop-v0.3.0", html_url: "https://github.com/Juhuaaaa/shutong/releases/tag/desktop-v0.3.0" } });
    const { wrapper, pinia } = await mountView(RouterView, "/logs");
    await useAuth(pinia).refresh();
    await vi.waitFor(() => expect(wrapper.find("[data-test=app-version]").text()).toBe("版本 0.3.0"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(wrapper.find("[data-test=app-update]").exists()).toBe(false);
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

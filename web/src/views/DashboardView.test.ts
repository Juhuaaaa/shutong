import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { useAuth } from "@/stores/auth";
import { fakeApi, status } from "@/test-utils";
import DashboardView from "./DashboardView.vue";

const data = {
  libraries: [
    { id: 1, name: "漫画", kind: "manga", series: 120, volumes: 1834, month_new: 46, planned: 12, needs_review: 3,
      failed: 1, available: true },
    { id: 2, name: "轻小说", kind: "novel", series: 30, volumes: 210, month_new: 0, planned: 0, needs_review: 0,
      failed: 0, available: false },
  ],
  recent: [
    { library_id: 1, group_key: "[极道超女]", series: "极道超女", subject_id: 9, image: "https://img/9", published: 19,
      at: new Date(Date.now() - 3600_000).toISOString() },
  ],
  jobs: [],
  storage: [{ path: "/media", total: 4000, used: 3000, free: 1000 }],
};

describe("DashboardView in the desktop app", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("says to drop files and offers no scanning", async () => {
    fakeApi({ "GET /api/dashboard": data, "GET /api/libraries": [] });
    const { wrapper, pinia } = await mountView(DashboardView, "/");
    useAuth(pinia).desktop = true;
    await vi.waitFor(() => expect(wrapper.find("[data-test=drop-hint]").exists()).toBe(true));
    expect(wrapper.find("[data-test=scan-1]").exists()).toBe(false);
    wrapper.unmount();
  });
});

describe("DashboardView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the numbers of each library", async () => {
    fakeApi({ "GET /api/dashboard": data, "GET /api/libraries": [] });
    const { wrapper } = await mountView(DashboardView, "/");
    await vi.waitFor(() => expect(wrapper.find("[data-test=library-stats]").exists()).toBe(true));
    const [manga, novel] = wrapper.findAll("[data-test=library-stats]");
    expect(manga.text()).toContain("漫画");
    expect(manga.find("[data-test=stat-volumes]").text()).toContain("1,834");
    expect(manga.find("[data-test=stat-month_new]").text()).toContain("46");
    expect(manga.find("[data-test=stat-needs_review]").text()).toContain("3");
    expect(novel.text()).toContain("目录不可用");
    expect(wrapper.find("[data-test=storage]").text()).toContain("75%");
  });

  it("links recent folders to their history", async () => {
    fakeApi({ "GET /api/dashboard": data, "GET /api/libraries": [] });
    const { wrapper, router } = await mountView(DashboardView, "/");
    await vi.waitFor(() => expect(wrapper.find("[data-test=recent]").exists()).toBe(true));
    const recent = wrapper.find("[data-test=recent]");
    expect(recent.text()).toContain("极道超女");
    expect(recent.text()).toContain("19");
    await recent.trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("history"));
    expect(router.currentRoute.value.path).toBe("/history");
    expect(router.currentRoute.value.query.group).toBe("1:[极道超女]");
  });

  it("scans a library from the quick actions", async () => {
    const { calls } = fakeApi({
      "GET /api/dashboard": data, "GET /api/libraries": [],
      "POST /api/libraries/1/scan": { job_id: 7 },
      "GET /api/jobs/7": { id: 7, kind: "scan", state: "done", result: { counts: { planned: 2 } } },
    });
    const { wrapper } = await mountView(DashboardView, "/");
    await vi.waitFor(() => expect(wrapper.find("[data-test=scan-1]").exists()).toBe(true));
    await wrapper.find("[data-test=scan-1]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/libraries/1/scan")).toBe(true));
  });

  it("shows the error instead of an empty page", async () => {
    fakeApi({ "GET /api/dashboard": status(500, "数据库坏了"), "GET /api/libraries": [] });
    const { wrapper } = await mountView(DashboardView, "/");
    await vi.waitFor(() => expect(wrapper.text()).toContain("数据库坏了"));
  });
});

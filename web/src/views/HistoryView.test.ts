import { afterEach, describe, expect, it, vi } from "vitest";
import { ask } from "@/composables/confirm";
import { fakeApi } from "@/test-utils";
import { mountView } from "@/test-mount";
import { useLibraries } from "@/stores/libraries";
import HistoryView from "./HistoryView.vue";

vi.mock("@/composables/confirm", () => ({ ask: vi.fn().mockResolvedValue(true) }));

function item(id: number, volume: string, status = "published") {
  return {
    id, library_id: 1, status, review_reason: null, source_path: `/s/迷宫饭/${id}.zip`, source_name: `${id}.zip`,
    parsed: { title_hint: "迷宫饭" }, subject_id: 133315, target_path: `迷宫饭/迷宫饭 ${volume}.cbz`,
    plan: { series: "迷宫饭", volume: `volume:${id}` }, error: null, overrides: {}, updated_at: "2026-10-30T07:00:00+00:00",
  };
}

function group(index: number, extra: object = {}) {
  return {
    library_id: 1, group_key: `目录${index}`, folder: `目录${index}`, series: `系列${index}`, subject_id: 9,
    counts: { published: 2, failed: 1 }, total: 3, updated_at: "2026-10-30T07:00:00+00:00", item_ids: [1, 2, 3], ...extra,
  };
}

function api(extra: Record<string, unknown> = {}) {
  return fakeApi({
    "GET /api/libraries": [{ id: 1, name: "漫画" }],
    "GET /api/libraries/1/summary": { counts: {} },
    "GET /api/history/groups": (_: unknown, url: URL) => {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return { groups: [group(offset + 1), group(offset + 2)], total: 75 };
    },
    "GET /api/history/groups/1/目录1": [item(1, "Vol.01"), item(2, "Vol.02"), item(3, "Vol.03", "failed")],
    "GET /api/items/1": { ...item(1, "Vol.01"), events: [
      { at: "2026-10-30T07:00:00+00:00", kind: "discovered", detail: {} },
      { at: "2026-10-30T07:01:00+00:00", kind: "review", detail: { note: "no volume number", series: "迷宫饭" } },
      { at: "2026-10-30T07:02:00+00:00", kind: "published", detail: { sha256: "ab", target: "迷宫饭/迷宫饭 Vol.01.cbz" } },
      { at: "2026-10-30T07:03:00+00:00", kind: "something_new", detail: {} },
    ], ai_calls: [] },
    ...extra,
  });
}

describe("HistoryView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("lists one row per source folder, paged on the server with filters in the address", async () => {
    const { calls } = api();
    const { wrapper, router } = await mountView(HistoryView, "/history?status=failed&q=迷宫");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=history-group]").length).toBe(2));
    const first = calls.find((call) => call.path === "/api/history/groups")!;
    expect(first).toBeTruthy();
    const row = wrapper.find("[data-test=history-group]");
    expect(row.text()).toContain("系列1");
    expect(row.text()).toContain("目录1");
    expect(row.text()).toContain("已整理 2");
    await wrapper.find("[data-test=next-page] button, [data-test=next-page]").trigger("click");
    await vi.waitFor(() => expect(wrapper.text()).toContain("系列31"));
    expect(router.currentRoute.value.query).toMatchObject({ status: "failed", q: "迷宫", page: "2" });
  });

  it("opens a folder sorted by volume and retries the whole folder when nothing is ticked", async () => {
    const { calls } = api({ "POST /api/items/retry": { job_id: 4 }, "GET /api/jobs/4": { id: 4, kind: "retry", state: "done", result: {} } });
    const { wrapper } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    expect(wrapper.findAll("[data-test=group-item]").map((row) => row.text().includes("Vol.01"))[0]).toBe(true);
    await wrapper.find("[data-test=group-retry]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/retry")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/retry")?.body).toEqual({ item_ids: [1, 2, 3] });
  });

  it("opens an item from an expanded folder", async () => {
    api();
    const { wrapper, router } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    await wrapper.findAll("[data-test=group-item] [data-test=item-details]")[0].trigger("click");
    await vi.waitFor(() => expect(document.querySelector("[data-test=timeline]")).not.toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(router.currentRoute.value.query.item).toBe("1");
    expect(document.querySelector("[data-test=item-drawer]")?.classList).toContain("v-navigation-drawer--active");
  });

  it("acts on the loaded items of a folder that is not on this page", async () => {
    const { calls } = api({
      "GET /api/history/groups/1/别处": [item(7, "Vol.01", "failed")],
      "POST /api/items/retry": { job_id: 4 }, "GET /api/jobs/4": { id: 4, kind: "retry", state: "done", result: {} },
    });
    const { wrapper } = await mountView(HistoryView, "/history?group=1:别处");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(1));
    await wrapper.find("[data-test=group-retry]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/retry")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/retry")?.body).toEqual({ item_ids: [7] });
  });

  it("refreshes the metadata of a folder's organized files and says what changed", async () => {
    const { calls } = api({
      "POST /api/items/refresh-metadata": { job_id: 7 },
      "GET /api/jobs/7": { id: 7, kind: "refresh_metadata", state: "done", result: { refreshed: 1, unchanged: 1, skipped: 0, failed: 0 } },
    });
    const { wrapper } = await mountView(HistoryView, "/history");
    await vi.waitFor(() => expect(wrapper.find("[data-test=history-group] .head").exists()).toBe(true));
    await wrapper.find("[data-test=history-group] .head").trigger("click");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    await wrapper.find("[data-test=group-refresh]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/refresh-metadata")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/refresh-metadata")?.body).toEqual({ item_ids: [1, 2] });
    await vi.waitFor(() => expect(document.body.textContent).toContain("更新 1 个，没变化 1 个"));
  });

  it("shows the cover from the address the server gives, a mirror included", async () => {
    api({ "GET /api/history/groups": { groups: [
      group(1, { image: "https://img.mirror.example/v0/subjects/9/image?type=small" }), group(2, { image: null })], total: 2 } });
    const { wrapper } = await mountView(HistoryView, "/history");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=history-group]").length).toBe(2));
    const rows = wrapper.findAll("[data-test=history-group]");
    expect(rows[0].find(".cover img").attributes("src")).toBe("https://img.mirror.example/v0/subjects/9/image?type=small");
    expect(rows[1].find(".cover img").exists()).toBe(false);
  });

  it("offers covers for manga only", async () => {
    api({
      "GET /api/libraries": [{ id: 1, name: "轻小说", kind: "novel" }],
    });
    const { wrapper, pinia } = await mountView(HistoryView, "/history");
    await useLibraries(pinia).refresh();
    await vi.waitFor(() => expect(wrapper.find("[data-test=history-group] .head").exists()).toBe(true));
    await wrapper.find("[data-test=history-group] .head").trigger("click");
    await vi.waitFor(() => expect(wrapper.find("[data-test=group-refresh]").exists()).toBe(true));
    expect(wrapper.find("[data-test=group-covers]").exists()).toBe(false);
  });

  it("asks before cancelling a whole folder", async () => {
    const { calls } = api({ "POST /api/items/cancel": { cancelled: 3, skipped: 0 } });
    vi.mocked(ask).mockClear();
    const { wrapper } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    await wrapper.find("[data-test=group-cancel]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/cancel")).toBe(true));
    expect(vi.mocked(ask).mock.calls[0][1]).toContain("3");
    expect(vi.mocked(ask).mock.calls[0][2]).toBe(true);
  });

  it("acts on the ticked volumes only", async () => {
    const { calls } = api({ "POST /api/items/retry": { job_id: 4 }, "GET /api/jobs/4": { id: 4, kind: "retry", state: "done", result: {} } });
    const { wrapper } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    await wrapper.findAll("[data-test=group-item] input[type=checkbox]")[2].setValue(true);
    await wrapper.find("[data-test=group-retry]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/retry")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/retry")?.body).toEqual({ item_ids: [3] });
  });

  it("keeps a folder of 867 chapters cheap to render", async () => {
    const many = Array.from({ length: 867 }, (_, index) => item(index + 1, `Ch.${String(index + 1).padStart(4, "0")}`));
    api({ "GET /api/history/groups/1/目录1": many });
    const { wrapper } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.find("[data-test=group-items]").exists()).toBe(true));
    expect(wrapper.findAll("[data-test=group-item]").length).toBeLessThan(100);
  });

  it("shows the timeline in words, never raw JSON", async () => {
    api();
    const { wrapper } = await mountView(HistoryView, "/history?item=1");
    await vi.waitFor(() => expect(document.body.textContent).toContain("发现来源"));
    const timeline = document.querySelector("[data-test=timeline]")!.textContent ?? "";
    expect(timeline).toContain("认不出卷号；系列：迷宫饭");
    expect(timeline).toContain("something_new");
    expect(timeline).not.toMatch(/[{}"]/);
    wrapper.unmount();
  });

  it("says so when a reorganize was refused because the source is gone", async () => {
    api({
      "POST /api/items/reorganize": { job_id: 3 },
      "GET /api/jobs/3": { id: 3, kind: "reorganize", state: "done", result: { trashed: 0, replanned: 0, skipped: 1 } },
    });
    const { notifyState } = await import("@/composables/notify");
    notifyState.queue.splice(0);
    const { wrapper } = await mountView(HistoryView, "/history?item=1");
    await vi.waitFor(() => expect(document.querySelector("[data-test=reorganize]")).not.toBeNull());
    (document.querySelector("[data-test=reorganize]") as HTMLElement).click();
    await vi.waitFor(() => expect(document.querySelector("[data-test=reorganize-submit]")).not.toBeNull());
    expect(document.querySelector("[data-test=reorganize-note]")?.textContent).toContain("不可恢复");
    (document.querySelector("[data-test=reorganize-submit]") as HTMLElement).click();
    await vi.waitFor(() => expect(notifyState.queue.map((entry) => entry.text).join()).toContain("来源文件已不在原处，未重新整理"));
    wrapper.unmount();
  });

  it("lists every library together and tags each folder with its kind", async () => {
    const { calls } = api({
      "GET /api/libraries": [{ id: 1, name: "漫画", kind: "manga" }, { id: 2, name: "轻小说", kind: "novel" }],
      "GET /api/libraries/2/summary": { counts: {} },
      "GET /api/history/groups": { groups: [group(1), group(2, { library_id: 2, group_key: "目录1", folder: "目录1" })], total: 2 },
    });
    const { wrapper, pinia } = await mountView(HistoryView, "/history");
    await useLibraries(pinia).refresh();
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=history-group]").length).toBe(2));
    expect(calls.find((call) => call.path === "/api/history/groups")!.url.searchParams.has("library_id")).toBe(false);
    expect(wrapper.findAll("[data-test=kind-tag]").map((tag) => tag.text())).toEqual(["漫画", "轻小说"]);
  });

  it("opens the folder of the right library when two share a name", async () => {
    api({
      "GET /api/history/groups": { groups: [group(1), group(1, { library_id: 2 })], total: 2 },
      "GET /api/history/groups/2/目录1": [{ ...item(5, "Vol.05"), library_id: 2 }],
    });
    const { wrapper } = await mountView(HistoryView, "/history?group=2:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(1));
    expect(wrapper.findAll("[data-test=history-group]")[1].find("[data-test=group-item]").exists()).toBe(true);
  });

  it("tags folders and files organized without metadata and filters them", async () => {
    const { calls } = api({
      "GET /api/history/groups": { groups: [group(1, { missing_metadata: 1 }), group(2)], total: 2 },
      "GET /api/history/groups/1/目录1": [{ ...item(1, "Vol.01"), subject_id: null }, item(2, "Vol.02")],
    });
    const { wrapper, router } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(2));
    const rows = wrapper.findAll("[data-test=history-group]");
    expect(rows[0].find(".head").text()).toContain("缺元数据 1");
    expect(rows[1].text()).not.toContain("缺元数据");
    const files = wrapper.findAll("[data-test=group-item]");
    expect(files[0].text()).toContain("缺元数据");
    expect(files[1].text()).not.toContain("缺元数据");
    await router.replace({ query: { status: "missing_metadata" } });
    await vi.waitFor(() => expect(calls.filter((call) => call.path === "/api/history/groups").length).toBe(2));
    const params = calls.filter((call) => call.path === "/api/history/groups")[1].url.searchParams;
    expect(params.get("missing_metadata")).toBe("true");
    expect(params.has("status")).toBe(false);
  });

  it("filters what deserves a second look: the AI's picks, or one source's entries", async () => {
    const { calls } = api();
    const { wrapper, router } = await mountView(HistoryView, "/history");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/history/groups")).toBe(true));
    expect(wrapper.text()).not.toContain("undefined");
    await router.replace({ query: { status: "ai_picked" } });
    await vi.waitFor(() => expect(calls.filter((call) => call.path === "/api/history/groups").length).toBe(2));
    let params = calls.filter((call) => call.path === "/api/history/groups")[1].url.searchParams;
    expect([params.get("ai_picked"), params.has("status")]).toEqual(["true", false]);
    await router.replace({ query: { status: "source:anilist" } });
    await vi.waitFor(() => expect(calls.filter((call) => call.path === "/api/history/groups").length).toBe(3));
    params = calls.filter((call) => call.path === "/api/history/groups")[2].url.searchParams;
    expect([params.get("source"), params.has("status")]).toEqual(["anilist", false]);
  });

  it("fills in metadata by hand for the organized volumes of a folder", async () => {
    const { calls } = api({
      "POST /api/items/metadata": { job_id: 6 },
      "GET /api/jobs/6": { id: 6, kind: "metadata", state: "done", result: { edited: 2, skipped: 0, failed: 0 } },
    });
    const { wrapper } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    await wrapper.find("[data-test=group-metadata]").trigger("click");
    await vi.waitFor(() => expect(document.querySelector("[data-test=metadata-dialog]")).not.toBeNull());
    (document.querySelector("[data-test=tab-manual]") as HTMLElement).click();
    await vi.waitFor(() => expect(document.querySelector("[data-test=field-summary] textarea")).not.toBeNull());
    const fill = (selector: string, value: string) => {
      const input = document.querySelector(selector) as HTMLInputElement;
      input.value = value;
      input.dispatchEvent(new Event("input"));
    };
    fill("[data-test=field-writers] input", "九井谅子、某人");
    fill("[data-test=field-summary] textarea", "迷宫里做饭");
    fill("[data-test=field-date] input", "2014-02");
    await wrapper.vm.$nextTick();
    (document.querySelector("[data-test=metadata-submit]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/metadata")).toBe(true));
    const body = calls.find((call) => call.path === "/api/items/metadata")!.body as Record<string, unknown>;
    expect(body.item_ids).toEqual([1, 2]);  // the failed one is not organized
    expect(body.fields).toMatchObject({ writers: ["九井谅子", "某人"], summary: "迷宫里做饭", release_date: "2014-02" });
    expect(body).not.toHaveProperty("bgm");
  });

  it("picks another Bangumi subject for a folder", async () => {
    const subject = { subject_id: "302561", source: "bangumi", web_url: "https://bgm.tv/subject/302561", aliases: [],
      name: "나 혼자만 레벨업", name_cn: "我独自升级", summary: "", writers: [],
      publisher: "", platform: "漫画", release_date: null, total_volumes: 14, image: null };
    const { calls } = api({
      "GET /api/metadata/search": [subject],
      "POST /api/items/metadata": { job_id: 7 },
      "GET /api/jobs/7": { id: 7, kind: "metadata", state: "done", result: { edited: 2, skipped: 0, failed: 0 } },
    });
    const { wrapper } = await mountView(HistoryView, "/history?group=1:目录1");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-item]").length).toBe(3));
    await wrapper.find("[data-test=group-metadata]").trigger("click");
    await vi.waitFor(() => expect(document.querySelector("[data-test=metadata-dialog] input")).not.toBeNull());
    const search = document.querySelector("[data-test=metadata-dialog] input") as HTMLInputElement;
    search.value = "我独自升级";
    search.dispatchEvent(new Event("input"));
    await wrapper.vm.$nextTick();
    [...document.querySelectorAll("[data-test=metadata-dialog] button")].find((button) => button.textContent?.trim() === "搜索")!
      .dispatchEvent(new MouseEvent("click"));
    await vi.waitFor(() => expect(calls.map((call) => call.path)).toContain("/api/metadata/search"));
    await vi.waitFor(() => expect(document.querySelector("[data-test=candidate]")).not.toBeNull());
    (document.querySelector("[data-test=candidate]") as HTMLElement).click();
    await wrapper.vm.$nextTick();
    (document.querySelector("[data-test=metadata-submit]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/metadata")).toBe(true));
    expect(calls.find((call) => call.path === "/api/items/metadata")!.body).toEqual({ item_ids: [1, 2],
      subject: { source: "bangumi", id: "302561" } });
  });

  it("shows the source folder only when it differs from the series name", async () => {
    api({ "GET /api/history/groups": { groups: [group(1), group(2, { series: null })], total: 2 } });
    const { wrapper } = await mountView(HistoryView, "/history");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=history-group]").length).toBe(2));
    const [named, unnamed] = wrapper.findAll("[data-test=history-group]");
    expect(named.find("[data-test=group-folder]").text()).toBe("目录1");
    expect(unnamed.find("[data-test=group-folder]").exists()).toBe(false);
    expect(unnamed.text()).toContain("目录2");
  });
});

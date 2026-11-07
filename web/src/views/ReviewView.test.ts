import { afterEach, describe, expect, it, vi } from "vitest";
import { ask } from "@/composables/confirm";
import { FakeSocket, fakeApi } from "@/test-utils";
import { mountView } from "@/test-mount";
import { useLibraries } from "@/stores/libraries";
import ReviewView from "./ReviewView.vue";

vi.mock("@/composables/confirm", () => ({ ask: vi.fn().mockResolvedValue(true) }));

function group(index: number, extra: object = {}) {
  return {
    key: `1:g${index}`, library_id: 1, folder: `[系列${index}][作者]`, reasons: ["metadata"], title_hint: `系列${index}`,
    edition: null, count: 2, item_ids: [index * 10 + 1, index * 10 + 2], sample_names: ["Vol.01.zip", "Vol.02.zip"],
    candidates: [], ai_suggestion: null, ...extra,
  };
}

const subject = {
  subject_id: 27684, name: "ドラえもん", name_cn: "哆啦A梦", summary: "", writers: ["藤子·F·不二雄"], publisher: "小学馆",
  platform: "漫画", release_date: "1974-07-31", total_volumes: 45, image: "https://example/cover.jpg",
};

const AI = { "ai.base_url": "https://api.deepseek.com/v1", "ai.api_key": "已设置", "ai.model": "deepseek-chat" };

function api(groups: unknown[], extra: Record<string, unknown> = {}) {
  return fakeApi({
    "GET /api/libraries": [{ id: 1, name: "漫画", kind: "manga" }],
    "GET /api/libraries/1/summary": { counts: {} },
    "GET /api/review/groups": groups,
    "GET /api/settings": AI,
    "GET /api/metadata/subjects/27684": subject,
    ...extra,
  });
}

describe("ReviewView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps a huge list cheap to render", async () => {
    api(Array.from({ length: 3000 }, (_, index) => group(index)));
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=detail]").text()).toContain("[系列0][作者]"));
    expect(wrapper.findAll("[data-test=group-row]").length).toBeLessThan(100);
    expect(wrapper.text()).toContain("3000");
  });

  it("fills the Bangumi id from a candidate", async () => {
    api([group(1, { candidates: [27684] })]);
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=candidate]").exists()).toBe(true));
    expect(wrapper.find("[data-test=candidate]").text()).toContain("藤子·F·不二雄");
    await wrapper.find("[data-test=candidate]").trigger("click");
    expect((wrapper.find("[data-test=bgm] input").element as HTMLInputElement).value).toBe("27684");
    expect((wrapper.find("[data-test=title] input").element as HTMLInputElement).value).toBe("哆啦A梦");
    // The label must float above a value set from a candidate, not sit on top of it.
    expect(wrapper.find("[data-test=bgm] .v-field").classes()).toContain("v-field--dirty");
  });

  it("picks a candidate with the keyboard", async () => {
    api([group(1, { candidates: [27684] })]);
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=candidate]").exists()).toBe(true));
    const candidate = wrapper.find("[data-test=candidate]");
    expect(candidate.attributes("role")).toBe("radio");
    expect(candidate.attributes("tabindex")).toBe("0");
    await candidate.trigger("keydown", { key: "Enter" });
    expect((wrapper.find("[data-test=bgm] input").element as HTMLInputElement).value).toBe("27684");
    expect(wrapper.find("[data-test=candidate]").attributes("aria-checked")).toBe("true");
  });

  it("asks for each volume when the reason is the volume, and checks the format", async () => {
    const { calls } = api([group(1, { reasons: ["volume"] })], {
      "GET /api/history/groups/1/[系列1][作者]": [
        { id: 11, source_name: "番外.zip", status: "needs_review" }, { id: 12, source_name: "特典.zip", status: "needs_review" },
      ],
    });
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=volume] input").length).toBe(2));
    const loads = calls.filter((call) => call.path.startsWith("/api/history/groups/1/") || call.path.startsWith("/api/items/"));
    expect(loads.map((call) => call.path)).toEqual(["/api/history/groups/1/[系列1][作者]"]);
    await wrapper.findAll("[data-test=volume] input")[0].setValue("第一卷");
    await vi.waitFor(() => expect(wrapper.text()).toContain("13、1.5、01-05、SP1"));
    expect(wrapper.find("[data-test=confirm]").attributes("disabled")).toBeDefined();
    await wrapper.findAll("[data-test=volume] input")[0].setValue("SP1");
    await vi.waitFor(() => expect(wrapper.find("[data-test=confirm]").attributes("disabled")).toBeUndefined());
  });

  describe("a folder of several works", () => {
    const ITEMS = [
      { id: 11, source_name: "某暗部的少女共栖 2X.epub", status: "needs_review", parsed: { title_hint: "某暗部的少女共栖", volume: "volume:2" } },
      { id: 12, source_name: "某暗部的少女共栖 3X.epub", status: "needs_review", parsed: { title_hint: "某暗部的少女共栖", volume: "volume:3" } },
      { id: 13, source_name: "某科学的超电磁炮SS.epub", status: "needs_review", parsed: { title_hint: "魔法禁书目录", volume: "special" } },
    ];
    const anbu = { ...subject, subject_id: 439286, name_cn: "某暗部的少女共栖", name: "とある暗部の少女共棲", platform: "小说" };

    function several(extra: Record<string, unknown> = {}) {
      return api([group(1, { key: "1:魔法禁书目录", folder: "魔法禁书目录", item_ids: [11, 12, 13], count: 3, reasons: ["volume"], title_hint: "魔法禁书目录" })], {
        "GET /api/libraries": [{ id: 1, name: "轻小说", kind: "novel" }],
        "GET /api/history/groups/1/魔法禁书目录": ITEMS,
        "GET /api/metadata/subjects/439286": anbu,
        "POST /api/review/confirm": { job_id: 9 },
        "GET /api/jobs/9": { id: 9, kind: "confirm", state: "done", result: { replanned: 2 } },
        ...extra,
      });
    }

    async function mounted() {
      const { wrapper, pinia } = await mountView(ReviewView, "/review");
      await useLibraries(pinia).refresh();
      await vi.waitFor(() => expect(wrapper.findAll("[data-test=file-row]").length).toBe(3));
      return wrapper;
    }

    it("confirms only the ticked files and leaves the rest in the group", async () => {
      const { calls } = several();
      const wrapper = await mounted();
      expect(wrapper.find("[data-test=confirm]").text()).toBe("确认这一组");
      await wrapper.findAll("[data-test=file-check] input")[2].setValue(false);
      expect(wrapper.find("[data-test=confirm]").text()).toBe("确认选中的 2 个");
      await wrapper.find("[data-test=title] input").setValue("某暗部的少女共栖");
      await wrapper.findAll("[data-test=volume] input")[0].setValue("2");
      await wrapper.findAll("[data-test=volume] input")[1].setValue("3");
      await wrapper.findAll("[data-test=volume] input")[2].setValue("SP1");
      await wrapper.find("[data-test=confirm]").trigger("click");
      await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/review/confirm")).toBe(true));
      expect(calls.find((call) => call.path === "/api/review/confirm")?.body)
        .toEqual({ item_ids: [11, 12], title: "某暗部的少女共栖", volumes: { 11: "2", 12: "3" } });
      expect(wrapper.find("[data-test=detail]").exists()).toBe(true);
    });

    it("ticks what the filter finds", async () => {
      several();
      const wrapper = await mounted();
      await wrapper.find("[data-test=file-filter] input").setValue("超电磁炮");
      expect(wrapper.findAll("[data-test=file-row]").length).toBe(1);
      await wrapper.find("[data-test=select-shown]").trigger("click");
      await wrapper.find("[data-test=file-filter] input").setValue("");
      expect(wrapper.find("[data-test=confirm]").text()).toBe("确认选中的 1 个");
      expect((wrapper.findAll("[data-test=file-check] input")[2].element as HTMLInputElement).checked).toBe(true);
      expect((wrapper.findAll("[data-test=file-check] input")[0].element as HTMLInputElement).checked).toBe(false);
    });

    it("offers the works the AI told apart", async () => {
      several();
      const wrapper = await mounted();
      const chips = wrapper.findAll("[data-test=ai-work]");
      expect(chips.map((chip) => chip.text())).toEqual(["某暗部的少女共栖 2", "魔法禁书目录 1"]);
      await chips[0].trigger("click");
      expect(wrapper.find("[data-test=confirm]").text()).toBe("确认选中的 2 个");
      expect((wrapper.find("[data-test=title] input").element as HTMLInputElement).value).toBe("某暗部的少女共栖");
    });

    it("finds a subject from a pasted Bangumi link", async () => {
      several();
      const wrapper = await mounted();
      await wrapper.find("[data-test=bangumi-search] input").setValue("https://bgm.tv/subject/439286");
      await wrapper.find("[data-test=bangumi-search] input").trigger("keyup.enter");
      await vi.waitFor(() => expect(wrapper.find("[data-test=candidate]").exists()).toBe(true));
      await wrapper.find("[data-test=candidate]").trigger("click");
      expect((wrapper.find("[data-test=bgm] input").element as HTMLInputElement).value).toBe("439286");
      expect((wrapper.find("[data-test=title] input").element as HTMLInputElement).value).toBe("某暗部的少女共栖");
    });

    it("takes a link in the Bangumi field too", async () => {
      several();
      const wrapper = await mounted();
      await wrapper.find("[data-test=bgm] input").setValue("https://bgm.tv/subject/439286");
      expect((wrapper.find("[data-test=bgm] input").element as HTMLInputElement).value).toBe("439286");
    });

    it("has no edition for a novel and no ranges in its volumes", async () => {
      several();
      const wrapper = await mounted();
      expect(wrapper.find("[data-test=edition]").exists()).toBe(false);
      await wrapper.findAll("[data-test=volume] input")[0].setValue("1-5");
      await vi.waitFor(() => expect(wrapper.find("[data-test=confirm]").attributes("disabled")).toBeDefined());
      expect(wrapper.text()).toContain("13、1.5、SP1");
    });

    it("shows what the AI read as a placeholder", async () => {
      several();
      const wrapper = await mounted();
      const inputs = wrapper.findAll("[data-test=volume] input");
      expect(inputs.map((input) => input.attributes("placeholder"))).toEqual(["2", "3", "SP"]);
    });
  });

  it("removes a confirmed group and moves to the next one", async () => {
    const { calls } = api([group(1), group(2)], {
      "POST /api/review/confirm": { job_id: 9 },
      "GET /api/jobs/9": { id: 9, kind: "confirm", state: "running", result: {} },
    });
    FakeSocket.instances = [];
    const { wrapper, pinia } = await mountView(ReviewView, "/review");
    const { useJobs } = await import("@/stores/jobs");
    useJobs(pinia).connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    await vi.waitFor(() => expect(wrapper.find("[data-test=detail]").text()).toContain("[系列1][作者]"));
    await wrapper.find("[data-test=title] input").setValue("迷宫饭");
    await wrapper.find("[data-test=confirm]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/review/confirm")).toBe(true));
    expect(calls.find((call) => call.path === "/api/review/confirm")?.body).toEqual({ item_ids: [11, 12], title: "迷宫饭" });
    FakeSocket.instances[0].push({ type: "job", job: { id: 9, kind: "confirm", state: "done", result: { replanned: 2 } } });
    await vi.waitFor(() => expect(wrapper.find("[data-test=detail]").text()).toContain("[系列2][作者]"));
    expect(wrapper.findAll("[data-test=group-row]").map((row) => row.text()).join()).not.toContain("[系列1]");
  });

  it("organizes a group without Bangumi when asked to skip recognition", async () => {
    const { calls } = api([group(1)], {
      "POST /api/review/confirm": { job_id: 9 },
      "GET /api/jobs/9": { id: 9, kind: "confirm", state: "done", result: { replanned: 2, executed: 2 } },
    });
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=skip-metadata]").exists()).toBe(true));
    expect(wrapper.find("[data-test=skip-metadata]").text()).toBe("跳过识别，直接整理");
    await wrapper.find("[data-test=title] input").setValue("");
    expect(wrapper.find("[data-test=skip-metadata]").attributes("disabled")).toBeDefined();
    await wrapper.find("[data-test=title] input").setValue("系列1");
    await wrapper.find("[data-test=skip-metadata]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/review/confirm")).toBe(true));
    expect(calls.find((call) => call.path === "/api/review/confirm")?.body)
      .toEqual({ item_ids: [11, 12], title: "系列1", skip_metadata: true });
  });

  it("keeps what you typed when the list reloads in the background", async () => {
    FakeSocket.instances = [];
    api([group(1)], { "GET /api/jobs/5": { id: 5, kind: "scan", state: "running", result: {} } });
    const { wrapper, pinia } = await mountView(ReviewView, "/review");
    const { useJobs } = await import("@/stores/jobs");
    const jobs = useJobs(pinia);
    jobs.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    await vi.waitFor(() => expect(wrapper.find("[data-test=detail]").exists()).toBe(true));
    await wrapper.find("[data-test=title] input").setValue("迷宫饭");
    jobs.submit(Promise.resolve({ job_id: 5 }), "扫描");
    await new Promise((resolve) => setTimeout(resolve, 0));
    FakeSocket.instances[0].push({ type: "job", job: { id: 5, kind: "scan", state: "done", result: {} } });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect((wrapper.find("[data-test=title] input").element as HTMLInputElement).value).toBe("迷宫饭");
  });

  it("reads one group again", async () => {
    const { calls } = api([group(1), group(2)], {
      "POST /api/review/reidentify": { job_id: 8 },
      "GET /api/jobs/8": { id: 8, kind: "reidentify", state: "done", result: { executed: 2, skipped: 0 } },
    });
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=reidentify-group]").exists()).toBe(true));
    await wrapper.find("[data-test=reidentify-group]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/review/reidentify")).toBe(true));
    expect(calls.find((call) => call.path === "/api/review/reidentify")?.body).toEqual({ item_ids: [11, 12] });
    await vi.waitFor(() => expect(document.body.textContent).toContain("入库 2"));
  });

  it("reads the whole library again after asking", async () => {
    const { calls } = api([group(1)], {
      "POST /api/review/reidentify": { job_id: 8 },
      "GET /api/jobs/8": { id: 8, kind: "reidentify", state: "done", result: { planned: 5, needs_review: 1, skipped: 0 } },
    });
    vi.mocked(ask).mockClear();
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=detail]").exists()).toBe(true));
    await wrapper.find("[data-test=reidentify-all]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/review/reidentify")).toBe(true));
    expect(calls.find((call) => call.path === "/api/review/reidentify")?.body).toEqual({ item_ids: [11, 12] });
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("says how many a re-read put straight into the library", async () => {
    api([group(1)], {
      "POST /api/review/reidentify": { job_id: 8 },
      "GET /api/jobs/8": { id: 8, kind: "reidentify", state: "done", result: { executed: 2, planned: 0, needs_review: 0, skipped: 0 } },
    });
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=reidentify-group]").exists()).toBe(true));
    await wrapper.find("[data-test=reidentify-group]").trigger("click");
    await vi.waitFor(() => expect(document.body.textContent).toContain("重新识别完成：入库 2，仍需复核 0"));
  });

  it("points to the AI settings when AI is not set up", async () => {
    api([group(1)], { "GET /api/settings": { "ai.base_url": "", "ai.api_key": "", "ai.model": "" } });
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=setup-ai]").exists()).toBe(true));
    expect(wrapper.find("[data-test=setup-ai]").text()).toContain("去设置 AI");
    expect(wrapper.find("[data-test=reidentify-group]").attributes("disabled")).toBeDefined();
  });

  it("shows what the AI made of the group and adopts it", async () => {
    api([group(1, { ai_suggestion: { title: "迷宫饭", edition: "bili电子版", subject_id: null, confidence: 0.6,
      reason: "目录名第二个方括号像书名", problem: null } })]);
    const { wrapper } = await mountView(ReviewView, "/review");
    await vi.waitFor(() => expect(wrapper.find("[data-test=detail]").text()).toContain("AI 的判断：迷宫饭"));
    expect(wrapper.find("[data-test=detail]").text()).toContain("把握 0.60");
    expect(wrapper.find("[data-test=setup-ai]").exists()).toBe(false);
    const adopt = wrapper.findAll("button").find((button) => button.text() === "采纳建议")!;
    await adopt.trigger("click");
    expect((wrapper.find("[data-test=title] input").element as HTMLInputElement).value).toBe("迷宫饭");
  });

  it("lists review folders of every library with their kind and uses the kind of the picked one", async () => {
    const { calls } = api([group(1), group(2, { key: "2:g2", library_id: 2 })], {
      "GET /api/libraries": [{ id: 1, name: "漫画", kind: "manga" }, { id: 2, name: "轻小说", kind: "novel" }],
      "GET /api/libraries/2/summary": { counts: {} },
      "GET /api/libraries/2/series": ["某轻小说 [台版]"],
    });
    const { wrapper, pinia } = await mountView(ReviewView, "/review");
    await useLibraries(pinia).refresh();
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=group-row]").length).toBe(2));
    expect(calls.find((call) => call.path === "/api/review/groups")!.url.searchParams.has("library_id")).toBe(false);
    expect(wrapper.findAll("[data-test=kind-tag]").map((tag) => tag.text())).toEqual(["漫画", "轻小说"]);
    await wrapper.findAll("[data-test=group-row]")[1].trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/libraries/2/series")).toBe(true));
  });
});

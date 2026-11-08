import { afterEach, describe, expect, it, vi } from "vitest";
import { mountWith } from "@/test-mount";
import { fakeApi, flush, status } from "@/test-utils";
import { ask } from "@/composables/confirm";
import { useAuth } from "@/stores/auth";
import LibraryCard from "./LibraryCard.vue";

vi.mock("@/composables/confirm", () => ({ ask: vi.fn().mockResolvedValue(true) }));

const library = {
  id: 1, name: "漫画", kind: "manga", source_dir: "/s", library_dir: "/l", naming_template: "", source_policy: "keep",
  archive_dir: null, pdf_to_cbz: true, overwrite_policy: "never", rename_files: true, available: true, server_id: null, server_library_id: null,
  watch: false,
};

function card(props: Record<string, unknown> = {}) {
  return mountWith(LibraryCard, { library, counts: {}, lastRun: null, servers: [], scanning: false, previewDelay: 0,
    expanded: true, ...props });
}

const save = (wrapper: ReturnType<typeof card>) => wrapper.find("[data-test=save]");

describe("LibraryCard", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("in the desktop app, offers only what applies to files dropped from anywhere", async () => {
    vi.stubGlobal("shutong", { openPath: vi.fn(), pickFolder: vi.fn(async () => "/选的") });
    fakeApi({});
    const wrapper = card({ library: { ...library, source_dir: "" } });
    expect(wrapper.find("[data-test=source-dir]").exists()).toBe(true);
    useAuth().desktop = true;
    await flush();
    expect(wrapper.find("[data-test=source-dir]").exists()).toBe(false);
    expect(wrapper.find("[data-test=watch]").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("整理后");
    await wrapper.find("[data-test=library-dir] .v-field__append-inner .v-icon").trigger("click");
    await flush();
    expect((wrapper.find("[data-test=library-dir] input").element as HTMLInputElement).value).toBe("/选的");
  });

  it("in the desktop app, opens the library folder instead of scanning", async () => {
    const openPath = vi.fn();
    vi.stubGlobal("shutong", { openPath });
    fakeApi({});
    const wrapper = card({ expanded: false });
    useAuth().desktop = true;
    await flush();
    expect(wrapper.find("[data-test=scan]").exists()).toBe(false);
    await wrapper.find("[data-test=open-folder]").trigger("click");
    expect(openPath).toHaveBeenCalledWith("/l");
  });

  it("shows why a template is bad and blocks saving", async () => {
    fakeApi({
      "POST /api/libraries/1/template-preview": (body: unknown) =>
        (body as { template: string }).template.endsWith("{ext}")
          ? { examples: [{ source: "迷宫饭 Vol.01.zip", target: "迷宫饭/Vol.01.cbz" }] }
          : status(422, "命名模板必须以 {ext} 结尾"),
    });
    const wrapper = card();
    await flush();
    await wrapper.find("[data-test=template] input").setValue("{series}");
    await vi.waitFor(() => expect(wrapper.text()).toContain("命名模板必须以 {ext} 结尾"));
    expect(save(wrapper).attributes("disabled")).toBeDefined();
    await wrapper.find("[data-test=template] input").setValue("{series}/{volume}{ext}");
    await vi.waitFor(() => expect(wrapper.text()).toContain("迷宫饭/Vol.01.cbz"));
    expect(save(wrapper).attributes("disabled")).toBeUndefined();
  });

  it("turns on directory watching", async () => {
    const { calls } = fakeApi({ "PATCH /api/libraries/1": { ...library, watch: true } });
    const wrapper = card();
    await flush();
    expect(wrapper.find("[data-test=watch]").text()).toContain("目录监控");
    await wrapper.find("[data-test=watch] input").setValue(true);
    await save(wrapper).trigger("click");
    await flush();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ watch: true });
  });

  it("leaves the source dir empty for an upload-only library", async () => {
    const { calls } = fakeApi({ "PATCH /api/libraries/1": { ...library, source_dir: "", source_policy: "delete" } });
    const wrapper = card({ library: { ...library, watch: true } });
    await flush();
    await wrapper.find("[data-test=source-dir] input").setValue("");
    expect(wrapper.text()).toContain("留空则只能在「上传」页添加文件");
    // Nothing to keep the originals in, and nothing to watch.
    expect(wrapper.find("[data-test=watch] input").attributes("disabled")).toBeDefined();
    expect(save(wrapper).attributes("disabled")).toBeUndefined();
    await save(wrapper).trigger("click");
    await flush();
    expect(calls.find((call) => call.method === "PATCH")?.body)
      .toEqual({ source_dir: "", source_policy: "delete", watch: false });
  });

  it("says an upload-only library takes files from the upload page", async () => {
    fakeApi({});
    const wrapper = card({ library: { ...library, source_dir: "", source_policy: "delete" }, expanded: false });
    await flush();
    expect(wrapper.find(".paths").text()).toContain("仅通过上传添加");
  });

  it("lists the template variables", async () => {
    fakeApi({});
    const wrapper = card();
    await flush();
    expect(wrapper.text()).toContain("{series}");
    expect(wrapper.text()).toContain("{ext}");
  });

  it("needs an archive folder for the archive policy", async () => {
    fakeApi({});
    const wrapper = card({ library: { ...library, source_policy: "archive" } });
    await flush();
    expect(wrapper.text()).toContain("需要填写原档目录");
    expect(save(wrapper).attributes("disabled")).toBeDefined();
  });

  it("sends only the changed fields", async () => {
    const { calls } = fakeApi({ "PATCH /api/libraries/1": library });
    const wrapper = card();
    await flush();
    await wrapper.find("[data-test=name] input").setValue("漫画库");
    await save(wrapper).trigger("click");
    await flush();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ name: "漫画库" });
    expect(wrapper.emitted("saved")).toBeTruthy();
  });

  it("leaves the edition to the naming template", async () => {
    fakeApi({});
    const wrapper = card();
    await flush();
    expect(wrapper.find("[data-test=include-edition]").exists()).toBe(false);
    expect(wrapper.text()).toContain("{author}");
    expect(wrapper.find("[data-test=template-guide]").attributes("href")).toContain("docs/guide.md#6-命名模板");
    expect(wrapper.find("[data-test=template] input").attributes("placeholder")).toBe("留空使用默认模板 {series}/{series} {volume}{ext}");
  });

  it("offers no edition for a novel library", async () => {
    fakeApi({});
    const wrapper = card({ library: { ...library, kind: "novel" } });
    await flush();
    expect(wrapper.text()).not.toContain("{edition}");
    expect(wrapper.text()).toContain("{author}");
  });

  it("offers what to do with a volume already in the library", async () => {
    fakeApi({});
    const wrapper = card();
    await flush();
    const select = wrapper.findComponent("[data-test=overwrite]") as unknown as { props: (name: string) => { title: string; value: string }[] };
    expect(select.props("items").map((entry) => [entry.value, entry.title])).toEqual([
      ["never", "不覆盖"], ["always", "总是覆盖"], ["larger", "按文件大小（留大的）"], ["newer", "保留最新"],
    ]);
  });

  it("keeps original file names when renaming is off", async () => {
    const { calls } = fakeApi({ "PATCH /api/libraries/1": { ...library, rename_files: false } });
    const wrapper = card();
    await flush();
    await wrapper.find("[data-test=rename-files] input").setValue(false);
    expect(wrapper.text()).toContain("模板只决定放在哪个目录");
    await save(wrapper).trigger("click");
    await flush();
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ rename_files: false });
  });

  it("refreshes a whole library's metadata after asking", async () => {
    const { calls } = fakeApi({
      "POST /api/items/refresh-metadata": { job_id: 3 },
      "GET /api/jobs/3": { id: 3, kind: "refresh_metadata", state: "done", result: { refreshed: 2, unchanged: 0, skipped: 1, failed: 0 } },
    });
    const wrapper = card({ expanded: false });
    await flush();
    await wrapper.find("[data-test=refresh-metadata]").trigger("click");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/items/refresh-metadata")).toBe(true));
    expect(ask).toHaveBeenCalledOnce();
    expect(calls.find((call) => call.path === "/api/items/refresh-metadata")?.body).toEqual({ library_id: 1 });
  });

  it("creates a library from an empty card", async () => {
    const { calls } = fakeApi({ "POST /api/libraries": { ...library, id: 2 } });
    const wrapper = card({ library: null });
    await flush();
    expect(save(wrapper).attributes("disabled")).toBeDefined();
    await wrapper.find("[data-test=name] input").setValue("轻小说");
    await wrapper.find("[data-test=source-dir] input").setValue("/media/downloads/novel");
    await wrapper.find("[data-test=library-dir] input").setValue("/media/novel");
    await save(wrapper).trigger("click");
    await flush();
    const body = calls.find((call) => call.method === "POST")?.body as Record<string, unknown>;
    expect([body.name, body.source_dir, "include_edition" in body]).toEqual(["轻小说", "/media/downloads/novel", false]);
  });

  it("collapsed shows the summary and asks to scan", async () => {
    fakeApi({});
    const wrapper = card({ expanded: false, counts: { planned: 4, needs_review: 2 } });
    await flush();
    expect(wrapper.find("[data-test=template]").exists()).toBe(false);
    expect(wrapper.text()).toContain("/s");
    await wrapper.find("[data-test=scan]").trigger("click");
    expect(wrapper.emitted("scan")).toBeTruthy();
  });
});

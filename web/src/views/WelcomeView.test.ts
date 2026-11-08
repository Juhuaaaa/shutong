import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { fakeApi, flush, status } from "@/test-utils";
import { useAuth } from "@/stores/auth";
import WelcomeView from "./WelcomeView.vue";

const settings = { "GET /api/settings": {}, "GET /api/ai/calls": [] };

function stubBridge() {
  vi.stubGlobal("shutong", {
    defaultLibraryDir: vi.fn(async (kind: string) => `/文档/书童库/${kind}`),
    pickFolder: vi.fn(async () => "/选的目录"),
  });
}

async function open(routes: Record<string, unknown>) {
  const api = fakeApi({ ...settings, ...routes });
  const { wrapper, router, pinia } = await mountView(WelcomeView, "/welcome");
  // The desktop app is the one with the bridge (stubBridge); without it this is the web version on a server.
  useAuth(pinia).desktop = "shutong" in window;
  await flush();
  return { api, wrapper, router };
}

describe("WelcomeView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("creates a manga and a novel library that keep the originals", async () => {
    stubBridge();
    const { api, wrapper } = await open({ "GET /api/libraries": [], "POST /api/libraries": { id: 1 }, "GET /api/libraries/1/summary": { counts: {} } });
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    const created = api.calls.filter((call) => call.method === "POST" && call.path === "/api/libraries").map((call) => call.body);
    expect(created).toEqual([
      expect.objectContaining({ kind: "manga", source_dir: "", source_policy: "keep", library_dir: "/文档/书童库/manga" }),
      expect.objectContaining({ kind: "novel", source_dir: "", source_policy: "keep", library_dir: "/文档/书童库/novel" }),
    ]);
    expect(wrapper.find("[data-test=step-ai]").exists()).toBe(true);
  });

  it("on a server, asks for the folders as the container sees them, and leaves out a library not wanted", async () => {
    const { api, wrapper } = await open({ "GET /api/libraries": [], "POST /api/libraries": { id: 1 },
      "GET /api/libraries/1/summary": { counts: {} } });
    expect(wrapper.find("[data-test=dir-manga]").exists()).toBe(false);  // the desktop's folder pickers
    expect(wrapper.find("[data-test=next-libraries]").attributes("disabled")).toBeDefined();
    await wrapper.find("[data-test=source-manga] input").setValue("/data/下载/漫画");
    await wrapper.find("[data-test=library-manga] input").setValue("/data/书库/漫画");
    await wrapper.find("[data-test=want-novel] input").setValue(false);
    expect(wrapper.find("[data-test=source-novel]").exists()).toBe(false);
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    const created = api.calls.filter((call) => call.method === "POST" && call.path === "/api/libraries").map((call) => call.body);
    expect(created).toEqual([expect.objectContaining({ kind: "manga", source_dir: "/data/下载/漫画",
      library_dir: "/data/书库/漫画", source_policy: "keep" })]);
    expect(wrapper.find("[data-test=step-ai]").exists()).toBe(true);
  });

  it("on a server, ends with how files come in there", async () => {
    const { wrapper } = await open({ "GET /api/libraries": [], "POST /api/libraries": { id: 1 },
      "GET /api/libraries/1/summary": { counts: {} }, "GET /api/metadata/sources": [{ name: "bangumi", label: "Bangumi", enabled: true }] });
    for (const kind of ["manga", "novel"]) {
      await wrapper.find(`[data-test=source-${kind}] input`).setValue(`/data/下载/${kind}`);
      await wrapper.find(`[data-test=library-${kind}] input`).setValue(`/data/书库/${kind}`);
    }
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    await wrapper.find("[data-test=later-ai]").trigger("click");
    await flush();
    await wrapper.find("[data-test=next-bangumi]").trigger("click");
    await flush();
    expect(wrapper.find("[data-test=step-done]").text()).toContain("扫描");
    expect(wrapper.find("[data-test=step-done]").text()).not.toContain("拖进窗口");
  });

  async function atAiStep(routes: Record<string, unknown>) {
    stubBridge();
    const opened = await open({ "GET /api/libraries": [], "POST /api/libraries": { id: 1 }, "GET /api/libraries/1/summary": { counts: {} }, ...routes });
    await opened.wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    await opened.wrapper.find("[data-test=ai-model] input").setValue("deepseek");
    return opened;
  }

  it("saves what was typed when going on from the AI step", async () => {
    const { api, wrapper } = await atAiStep({ "PATCH /api/settings": {} });
    await wrapper.find("[data-test=next-ai]").trigger("click");
    await flush();
    expect(api.calls.find((call) => call.method === "PATCH")?.body).toEqual({ "ai.model": "deepseek" });
    expect(wrapper.find("[data-test=step-bangumi]").exists()).toBe(true);
  });

  it("stays on the AI step when saving fails", async () => {
    const { wrapper } = await atAiStep({ "PATCH /api/settings": status(422, "地址不对") });
    await wrapper.find("[data-test=next-ai]").trigger("click");
    await flush();
    expect(wrapper.find("[data-test=step-ai]").exists()).toBe(true);
  });

  it("does not save when putting the AI off", async () => {
    const { api, wrapper } = await atAiStep({});
    await wrapper.find("[data-test=later-ai]").trigger("click");
    await flush();
    expect(api.calls.some((call) => call.method === "PATCH")).toBe(false);
    expect(wrapper.find("[data-test=step-bangumi]").exists()).toBe(true);
  });

  it("uses the folder picked in the native dialog", async () => {
    stubBridge();
    const { wrapper } = await open({ "GET /api/libraries": [] });
    await wrapper.find("[data-test=dir-manga] .v-field__append-inner .v-icon").trigger("click");
    await flush();
    expect((wrapper.find("[data-test=dir-manga] input").element as HTMLInputElement).value).toBe("/选的目录");
  });

  it("does not create a library twice when retrying after a failure", async () => {
    stubBridge();
    let lists = 0;
    const { api, wrapper } = await open({
      "GET /api/libraries": () => (lists++ ? [{ id: 1, kind: "manga" }] : []),
      "POST /api/libraries": (body: { kind: string }) => (body.kind === "novel" && lists === 1 ? status(422, "目录不能用") : { id: 2 }),
      "GET /api/libraries/1/summary": { counts: {} },
    });
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    expect(wrapper.find("[data-test=error]").text()).toContain("目录不能用");
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    const kinds = api.calls.filter((call) => call.method === "POST").map((call) => (call.body as { kind: string }).kind);
    expect(kinds).toEqual(["manga", "novel", "novel"]);
  });

  it("tells what is sent to the AI, and AI can wait", async () => {
    stubBridge();
    const created: object[] = [];  // the library list once one was made, as the server would answer
    const { wrapper, router } = await open({ "GET /api/libraries": () => created,
      "POST /api/libraries": (body: object) => { created.push({ id: 1, ...body }); return { id: 1 }; },
      "GET /api/libraries/1/summary": { counts: {} } });
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    expect(wrapper.find("[data-test=privacy]").text()).toContain("文件名");
    await wrapper.find("[data-test=later-ai]").trigger("click");
    await wrapper.find("[data-test=next-bangumi]").trigger("click");
    await wrapper.find("[data-test=finish]").trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("dashboard"));
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { fakeApi, flush, status } from "@/test-utils";
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
  const { wrapper, router } = await mountView(WelcomeView, "/welcome");
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
    const { wrapper, router } = await open({ "GET /api/libraries": [], "POST /api/libraries": { id: 1 }, "GET /api/libraries/1/summary": { counts: {} } });
    await wrapper.find("[data-test=next-libraries]").trigger("click");
    await flush();
    expect(wrapper.find("[data-test=privacy]").text()).toContain("文件名");
    await wrapper.find("[data-test=later-ai]").trigger("click");
    await wrapper.find("[data-test=next-bangumi]").trigger("click");
    await wrapper.find("[data-test=finish]").trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("dashboard"));
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { ask } from "@/composables/confirm";
import { fakeApi } from "@/test-utils";
import { mountView } from "@/test-mount";
import SettingsView from "./SettingsView.vue";

vi.mock("@/composables/confirm", () => ({ ask: vi.fn().mockResolvedValue(true) }));

const settings = {
  "bangumi.base_url": "https://api.bgm.tv", "bangumi.token": "", "metadata.sources": ["bangumi"], "ai.base_url": "https://api.deepseek.com/v1",
  "ai.api_key": "已设置", "ai.model": "deepseek-chat", "ai.threshold": 0.95, "network.proxy": "", "ai.use_proxy": false,
};

function api(extra: Record<string, unknown> = {}) {
  return fakeApi({
    "GET /api/libraries": [{ id: 1, name: "漫画", kind: "manga" }], "GET /api/libraries/1/summary": { counts: {} }, "GET /api/settings": settings, "PATCH /api/settings": (body: object) => ({ ...settings, ...body }),
    "GET /api/ai/calls": [], "GET /api/servers": [],
    "GET /api/metadata/sources": [{ name: "bangumi", label: "Bangumi", enabled: true }, { name: "anilist", label: "AniList", enabled: false }],
    ...extra,
  });
}

function input(selector: string) {
  // A combobox carries a hidden input too: the one typed into is the visible one.
  return document.querySelector(`[data-test=${selector}] input:not([type=hidden])`) as HTMLInputElement;
}

async function type(selector: string, value: string) {
  const element = input(selector);
  element.value = value;
  element.dispatchEvent(new Event("input"));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("SettingsView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("sends only what changed and leaves the untouched key alone", async () => {
    const { calls } = api();
    await mountView(SettingsView, "/settings/ai");
    await vi.waitFor(() => expect(input("ai-threshold")?.value).toBe("0.95"));
    await type("ai-threshold", "0.9");
    input("ai-threshold").dispatchEvent(new Event("blur"));
    (document.querySelector("[data-test=save-ai]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ "ai.threshold": 0.9 });
  });

  it("switches on a second metadata source, moves it first and saves the order", async () => {
    const { calls } = api();
    await mountView(SettingsView, "/settings/metadata");
    await vi.waitFor(() => expect(document.querySelector("[data-test=source-anilist]")).not.toBeNull());
    const only = document.querySelector("[data-test=source-switch-bangumi] input") as HTMLInputElement;
    only.click(); // the last one switched on stays on, and still looks on
    await new Promise((resolve) => setTimeout(resolve, 0));
    const after = document.querySelector("[data-test=source-switch-bangumi] input") as HTMLInputElement;
    expect(after.disabled).toBe(false);
    expect(after.checked).toBe(true);
    expect(document.body.textContent).toContain("至少要开一个数据源");
    (document.querySelector("[data-test=source-switch-anilist] input") as HTMLInputElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    (document.querySelector("[data-test=source-up-anilist]") as HTMLElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    (document.querySelector("[data-test=save-metadata]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ "metadata.sources": ["anilist", "bangumi"] });
  });

  it("shows the sources the server really asks, whatever was stored", async () => {
    api({ "GET /api/settings": { ...settings, "metadata.sources": ["douban"] } });
    await mountView(SettingsView, "/settings/metadata");
    await vi.waitFor(() => expect(document.querySelector("[data-test=source-switch-bangumi] input")).not.toBeNull());
    expect((document.querySelector("[data-test=source-switch-bangumi] input") as HTMLInputElement).checked).toBe(true);
  });

  it("turns the summary translation off", async () => {
    const { calls } = api({ "GET /api/settings": { ...settings, "metadata.translate_summaries": true } });
    await mountView(SettingsView, "/settings/metadata");
    await vi.waitFor(() => expect((document.querySelector("[data-test=translate-summaries] input") as HTMLInputElement)?.checked).toBe(true));
    (document.querySelector("[data-test=translate-summaries] input") as HTMLInputElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    (document.querySelector("[data-test=save-metadata]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ "metadata.translate_summaries": false });
  });

  it("saves a mirror for Bangumi images", async () => {
    const { calls } = api({ "GET /api/settings": { ...settings, "bangumi.image_base_url": "" } });
    await mountView(SettingsView, "/settings/metadata");
    await vi.waitFor(() => expect(input("bangumi-image-url")).not.toBeNull());
    await vi.waitFor(() => expect(input("translate-summaries") ?? true).toBeTruthy());
    await new Promise((resolve) => setTimeout(resolve, 50));
    await type("bangumi-image-url", "https://img.mirror.example");
    (document.querySelector("[data-test=save-metadata]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ "bangumi.image_base_url": "https://img.mirror.example" });
  });

  it("offers the official Bangumi addresses and known mirrors, and names the personal token", async () => {
    api({ "GET /api/settings": { ...settings, "metadata.sources": ["bangumi"] } });
    const { wrapper } = await mountView(SettingsView, "/settings/metadata");
    await vi.waitFor(() => expect(input("bangumi-url")).not.toBeNull());
    expect(document.body.textContent).toContain("个人令牌");
    expect(document.body.textContent).not.toContain("Access Token");
    expect(document.querySelector("[data-test=bangumi-token-link]")?.getAttribute("href")).toBe("https://next.bgm.tv/demo/access-token");
    // The lists only render when opened: read what each field offers.
    const offered = (selector: string) => (wrapper.findComponent(`[data-test=${selector}]`) as unknown as
      { props: (name: string) => string[] }).props("items");
    expect(offered("bangumi-url")).toEqual(["https://api.bgm.tv", "https://bgmapi.anibt.net"]);
    expect(offered("bangumi-image-url")).toEqual(["https://lain.bgm.tv", "https://bgmimg.anibt.net"]);
  });

  it("still opens the metadata tab from an old Bangumi link", async () => {
    api();
    await mountView(SettingsView, "/settings/bangumi");
    await vi.waitFor(() => expect(document.querySelector("[data-test=sources]")).not.toBeNull());
  });

  it("opens on the AI tab, which says scanning needs it", async () => {
    api();
    await mountView(SettingsView, "/settings");
    await vi.waitFor(() => expect(document.querySelector("[data-test=ai-required]")).not.toBeNull());
    expect(document.body.textContent).toContain("填好接口地址、API Key 和模型后才能扫描");
    for (const gone of ["回收目录", "识别出来就直接入库", "自动采纳", "启用 AI"]) {
      expect(document.body.textContent).not.toContain(gone);
    }
  });

  it("has no daily limit and sends the AI proxy switch", async () => {
    const { calls } = api();
    await mountView(SettingsView, "/settings/ai");
    await vi.waitFor(() => expect(input("ai-use-proxy")).not.toBeNull());
    expect(document.body.textContent).not.toContain("每日");
    input("ai-use-proxy").click();
    (document.querySelector("[data-test=save-ai]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ "ai.use_proxy": true });
  });

  it("checks the proxy address and tests it", async () => {
    const { calls } = api({ "POST /api/settings/proxy-test": { ok: true, error: null, elapsed_ms: 321 } });
    await mountView(SettingsView, "/settings/network");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/settings")).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 0));
    await type("proxy", "192.168.1.2:7890");
    await vi.waitFor(() => expect(document.body.textContent).toContain("代理地址格式不对"));
    expect((document.querySelector("[data-test=save-network]") as HTMLButtonElement).disabled).toBe(true);
    await type("proxy", "socks5://192.168.1.2:7891");
    (document.querySelector("[data-test=test-proxy]") as HTMLElement).click();
    await vi.waitFor(() => expect(document.body.textContent).toContain("321 ms"));
    expect(calls.find((call) => call.path === "/api/settings/proxy-test")?.body).toEqual({ proxy: "socks5://192.168.1.2:7891" });
  });

  it("keeps unsaved edits when switching tabs", async () => {
    const { calls } = api();
    const { router } = await mountView(SettingsView, "/settings/network");
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/settings")).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 0));
    await type("proxy", "http://192.168.1.2:7890");
    await router.replace({ name: "settings", params: { tab: "ai" } });
    await vi.waitFor(() => expect(input("ai-threshold")).not.toBeNull());
    await router.replace({ name: "settings", params: { tab: "network" } });
    await vi.waitFor(() => expect(input("proxy")?.value).toBe("http://192.168.1.2:7890"));
  });

  it("asks before changing the password", async () => {
    const { calls } = api({ "POST /api/auth/password": { ok: true } });
    vi.mocked(ask).mockClear();
    await mountView(SettingsView, "/settings/account");
    await vi.waitFor(() => expect(input("old-password")).not.toBeNull());
    await type("old-password", "old password");
    await type("new-password", "new password 1");
    await type("repeat-password", "new password 1");
    (document.querySelector("[data-test=change-password]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.path === "/api/auth/password")).toBe(true));
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("stops showing a cleared key as set", async () => {
    let stored = { ...settings };
    api({ "GET /api/settings": () => stored, "PATCH /api/settings": (body: object) => (stored = { ...stored, ...body }) });
    await mountView(SettingsView, "/settings/ai");
    await vi.waitFor(() => expect(document.querySelector("[data-test=clear-ai-key]")).not.toBeNull());
    (document.querySelector("[data-test=clear-ai-key]") as HTMLElement).click();
    await vi.waitFor(() => expect(document.querySelector("[data-test=clear-ai-key]")).toBeNull());
  });

  it("clears a stored key only through its own button", async () => {
    const { calls } = api();
    await mountView(SettingsView, "/settings/ai");
    await vi.waitFor(() => expect(document.querySelector("[data-test=clear-ai-key]")).not.toBeNull());
    (document.querySelector("[data-test=clear-ai-key]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")?.body).toEqual({ "ai.api_key": "" });
  });

  it("does not send a password change when the two entries differ", async () => {
    const { calls } = api();
    await mountView(SettingsView, "/settings/account");
    await vi.waitFor(() => expect(input("old-password")).not.toBeNull());
    await type("old-password", "old password");
    await type("new-password", "new password 1");
    await type("repeat-password", "new password 2");
    (document.querySelector("[data-test=change-password]") as HTMLElement).click();
    await vi.waitFor(() => expect(document.body.textContent).toContain("两次输入的新密码不一致"));
    expect(calls.some((call) => call.path === "/api/auth/password")).toBe(false);
  });

  it("switches the interface language on the account tab", async () => {
    fakeApi({ "GET /api/settings": {} });
    const { wrapper } = await mountView(SettingsView, "/settings/account", { tab: "account" });
    await vi.waitFor(() => expect(wrapper.find("[data-test=language]").exists()).toBe(true));
    const select = wrapper.findComponent("[data-test=language]") as unknown as { vm: { $emit: (name: string, value: string) => void } };
    select.vm.$emit("update:modelValue", "en");
    await vi.waitFor(() => expect(wrapper.text()).toContain("Change password"));
    select.vm.$emit("update:modelValue", "zh-CN");
    await vi.waitFor(() => expect(wrapper.text()).toContain("修改密码"));
  });

  it("shows each server with its own app icon", async () => {
    api({ "GET /api/servers": [
      { id: 1, kind: "kavita", name: "家里", base_url: "http://k:5000", username: "u", enabled: true, password_set: true },
      { id: 2, kind: "komga", name: "书库", base_url: "http://g:25600", username: "a@b.c", enabled: true, password_set: true }] });
    await mountView(SettingsView, "/settings/servers");
    await vi.waitFor(() => expect(document.querySelectorAll("[data-test=server-icon]").length).toBe(2));
    const sources = [...document.querySelectorAll("[data-test=server-icon] img")].map((img) => img.getAttribute("src"));
    expect(sources[0]).toContain("kavita");
    expect(sources[1]).toContain("komga");
    expect(document.body.textContent).toContain("Komga · http://g:25600");
  });

  it("adds a Komga server, which logs in with an email", async () => {
    const { calls } = api({ "POST /api/servers": (body: object) => ({ id: 1, enabled: true, ...body }) });
    const { wrapper } = await mountView(SettingsView, "/settings/servers", { tab: "servers" });
    await vi.waitFor(() => expect(document.querySelector("[data-test=server-add]")).not.toBeNull());
    (document.querySelector("[data-test=server-add]") as HTMLElement).click();
    await vi.waitFor(() => expect(wrapper.findComponent("[data-test=server-kind]").exists()).toBe(true));
    const kind = wrapper.findComponent("[data-test=server-kind]") as unknown as { vm: { $emit: (name: string, value: string) => void } };
    kind.vm.$emit("update:modelValue", "komga");
    await vi.waitFor(() => expect(document.body.textContent).toContain("在系列标题中添加卷号"));
    expect(document.body.textContent).toContain("邮箱");
    (document.querySelector("[data-test=server-save]") as HTMLElement).click();
    await vi.waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({ kind: "komga", name: "komga" });
  });
});

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import { i18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { testVuetify } from "@/test-mount";
import { fakeApi, flush } from "@/test-utils";
import LoginView from "./LoginView.vue";

async function mountAt(path: string) {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  const wrapper = mount(LoginView, { global: { plugins: [router, i18n, testVuetify()] }, attachTo: document.body });
  await flush();
  return { wrapper, router };
}

describe("LoginView", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.unstubAllGlobals());

  it("asks for a new password on first use and checks its length", async () => {
    const { calls } = fakeApi({ "GET /api/auth/status": { configured: false, logged_in: false } });
    const { wrapper } = await mountAt("/login");
    expect(wrapper.text()).toContain("首次使用");
    await wrapper.find("input[type=password]").setValue("short");
    await wrapper.find("form").trigger("submit");
    await flush();
    expect(wrapper.text()).toContain("密码至少 8 位");
    expect(calls.some((call) => call.path === "/api/auth/setup")).toBe(false);
  });

  it("logs in and goes back to the page that asked", async () => {
    let loggedIn = false;
    fakeApi({
      "GET /api/auth/status": () => ({ configured: true, logged_in: loggedIn }),
      "POST /api/auth/login": () => {
        loggedIn = true;
        return { ok: true };
      },
    });
    const { wrapper, router } = await mountAt("/login?next=/logs");
    await wrapper.find("input[type=password]").setValue("correct horse");
    await wrapper.find("form").trigger("submit");
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe("/logs"));
  });
});

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory } from "vue-router";
import { fakeApi } from "@/test-utils";
import { createAppRouter } from "./router";

describe("router guard", () => {
  beforeEach(() => setActivePinia(createPinia()));
  afterEach(() => vi.unstubAllGlobals());

  it("sends anonymous users to the login page with the way back", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: false } });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/logs");
    expect(router.currentRoute.value.fullPath).toBe("/login?next=/logs");
  });

  it("lets logged-in users through", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: true } });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/logs");
    expect(router.currentRoute.value.path).toBe("/logs");
  });

  it("opens the desktop app on the welcome page until it has a library", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: true }, "GET /api/libraries": [] });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/");
    expect(router.currentRoute.value.name).toBe("welcome");
  });

  it("goes straight in when the desktop app has a library, and has no upload page", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: true },
      "GET /api/libraries": [{ id: 1 }], "GET /api/libraries/1/summary": { counts: {} } });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/review");
    expect(router.currentRoute.value.name).toBe("review");
    await router.push("/upload");
    expect(router.currentRoute.value.name).toBe("dashboard");
  });

  it("opens the web version on the welcome page too until it has a library, and keeps its upload page", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: false }, "GET /api/libraries": [] });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/");
    expect(router.currentRoute.value.name).toBe("welcome");
  });

  it("lets the web version with a library use its upload page", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: true, desktop: false },
      "GET /api/libraries": [{ id: 1 }], "GET /api/libraries/1/summary": { counts: {} } });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/upload");
    expect(router.currentRoute.value.name).toBe("upload");
  });

  it("sends old per-library review and history links to the merged pages", async () => {
    fakeApi({ "GET /api/auth/status": { configured: true, logged_in: true } });
    const router = createAppRouter(createMemoryHistory());
    await router.push("/libraries/3/history?group=x");
    expect(router.currentRoute.value.fullPath).toBe("/history?group=x");
    await router.push("/libraries/3/review");
    expect(router.currentRoute.value.path).toBe("/review");
  });
});

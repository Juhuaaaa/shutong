import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import { settings as settingsApi } from "@/api";
import { useAuth } from "@/stores/auth";
import { useLibraries } from "@/stores/libraries";

/** The desktop app has nothing to do without a library; a server may run without one once its wizard was skipped. */
async function wizardDone(desktop: boolean): Promise<boolean> {
  if (desktop) return false;
  try {
    return (await settingsApi.get())["welcome.done"] === true;
  } catch {
    return false;
  }
}

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      { path: "/login", name: "login", component: () => import("@/views/LoginView.vue") },
      { path: "/welcome", name: "welcome", component: () => import("@/views/WelcomeView.vue"), meta: { auth: true } },
      {
        path: "/",
        component: () => import("@/layouts/AppLayout.vue"),
        meta: { auth: true },
        children: [
          { path: "", name: "dashboard", component: () => import("@/views/DashboardView.vue") },
          { path: "upload", name: "upload", component: () => import("@/views/UploadView.vue") },
          { path: "libraries", name: "libraries", component: () => import("@/views/LibrariesView.vue") },
          { path: "review", name: "review", component: () => import("@/views/ReviewView.vue") },
          { path: "history", name: "history", component: () => import("@/views/HistoryView.vue") },
          // Links saved before review and history covered every library.
          { path: "libraries/:id/review", redirect: (to) => ({ name: "review", query: to.query }) },
          { path: "libraries/:id/history", redirect: (to) => ({ name: "history", query: to.query }) },
          { path: "settings/:tab?", name: "settings", component: () => import("@/views/SettingsView.vue") },
          { path: "logs", name: "logs", component: () => import("@/views/LogsView.vue") },
        ],
      },
      { path: "/:pathMatch(.*)*", redirect: "/" },
    ],
  });

  router.beforeEach(async (to) => {
    if (!to.matched.some((record) => record.meta.auth)) return true;
    const auth = useAuth();
    if (!auth.loggedIn) {
      try {
        await auth.refresh();
      } catch {
        return { path: "/login", query: { next: to.fullPath } };
      }
    }
    if (!auth.loggedIn) return { path: "/login", query: { next: to.fullPath } };
    if (to.name !== "welcome") {
      if (auth.desktop && to.name === "upload") return { name: "dashboard" }; // the whole window takes drops
      const libraries = useLibraries();
      if (!libraries.loaded) await libraries.refresh().catch(() => {});
      if (libraries.loaded && !libraries.list.length && !(await wizardDone(auth.desktop))) return { name: "welcome" };
    }
    return true;
  });

  return router;
}

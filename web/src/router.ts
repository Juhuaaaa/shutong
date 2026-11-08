import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import { useAuth } from "@/stores/auth";
import { useLibraries } from "@/stores/libraries";

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
      if (libraries.loaded && !libraries.list.length) return { name: "welcome" };
    }
    return true;
  });

  return router;
}

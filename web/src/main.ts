import { createPinia } from "pinia";
import { createApp } from "vue";
import "vuetify/styles";
import "./styles/main.scss";
import App from "./App.vue";
import { setUnauthorizedHandler } from "./api/client";
import { storedThemeMode } from "./composables/themeMode";
import { i18n } from "./i18n";
import { createAppVuetify } from "./plugins/vuetify";
import { createAppRouter } from "./router";
import { useAuth } from "./stores/auth";

const pinia = createPinia();
const router = createAppRouter();

setUnauthorizedHandler(() => {
  useAuth(pinia).expired();
  const current = router.currentRoute.value;
  if (current.name !== "login") router.replace({ path: "/login", query: { next: current.fullPath } });
});

createApp(App).use(pinia).use(router).use(i18n).use(createAppVuetify(storedThemeMode())).mount("#app");

/** Mount a view inside the providers it needs (Vuetify, i18n, router, pinia). */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, h, type Component } from "vue";
import { createMemoryHistory } from "vue-router";
import { VApp } from "vuetify/components";
import AppNotify from "@/components/AppNotify.vue";
import { notifyState } from "@/composables/notify";
import { i18n } from "@/i18n";
import { createAppVuetify } from "@/plugins/vuetify";
import { createAppRouter } from "@/router";
import { useAuth } from "@/stores/auth";

export function testVuetify() {
  return createAppVuetify("light");
}

export async function mountView(view: Component, path: string, props: Record<string, unknown> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuth(pinia).loggedIn = true; // views are tested logged in; the guard has its own tests
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  notifyState.queue.splice(0);
  const host = defineComponent({
    render: () => h(VApp, null, () => [
      h(view, props),
      h(AppNotify),
    ]),
  });
  const wrapper = mount(host, { global: { plugins: [pinia, router, i18n, testVuetify()] }, attachTo: document.body });
  return { wrapper, router, pinia };
}

/** Mount a single component with Vuetify, i18n and a fresh pinia (no router). */
export function mountWith(component: Component, props: Record<string, unknown> = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(component, { props, global: { plugins: [pinia, i18n, testVuetify()] }, attachTo: document.body });
}

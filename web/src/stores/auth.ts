import { defineStore } from "pinia";
import { ref } from "vue";
import { auth as api } from "@/api";

export const useAuth = defineStore("auth", () => {
  const configured = ref(true);
  const loggedIn = ref(false);
  const checked = ref(false);
  const desktop = ref(false);
  const version = ref("");

  async function refresh() {
    const status = await api.status();
    configured.value = status.configured;
    loggedIn.value = status.logged_in;
    desktop.value = status.desktop ?? false;
    version.value = status.version ?? "";
    checked.value = true;
    return status;
  }

  async function login(password: string) {
    await api.login(password);
    loggedIn.value = true;
  }

  async function setup(password: string) {
    await api.setup(password);
    configured.value = true;
    loggedIn.value = true;
  }

  async function logout() {
    try {
      await api.logout();
    } finally {
      loggedIn.value = false;
    }
  }

  function expired() {
    loggedIn.value = false;
  }

  return { version, configured, loggedIn, checked, desktop, refresh, login, setup, logout, expired };
});

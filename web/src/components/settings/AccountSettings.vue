<script setup lang="ts">
import { mdiLogout } from "@mdi/js";
import { reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { useLocale } from "vuetify";
import { auth as api } from "@/api";
import type { ApiError } from "@/api/client";
import { ask } from "@/composables/confirm";
import { notify } from "@/composables/notify";
import { LOCALES, setLocale, type Locale } from "@/i18n";
import { useAuth } from "@/stores/auth";

const { t, locale } = useI18n();
const vuetifyLocale = useLocale();
const router = useRouter();
const auth = useAuth();
const form = reactive({ old: "", next: "", repeat: "" });
const error = ref("");

function changeLanguage(value: string) {
  setLocale(value as Locale);
  vuetifyLocale.current.value = value === "en" ? "en" : "zhHans";
}

async function change() {
  error.value = "";
  if (form.next.length < 8) error.value = t("login.tooShort");
  else if (form.next !== form.repeat) error.value = t("settings.passwordMismatch");
  if (error.value) return;
  if (!(await ask(t("settings.changePasswordTitle"), t("settings.changePasswordText")))) return;
  try {
    await api.changePassword(form.old, form.next);
    Object.assign(form, { old: "", next: "", repeat: "" });
    notify.success(t("settings.passwordChanged"));
  } catch (reason) {
    error.value = (reason as ApiError).detail ?? String(reason);
  }
}

async function logout() {
  await auth.logout();
  await router.push("/login");
}
</script>

<template>
  <div class="form">
    <VSelect :model-value="locale" :items="[...LOCALES]" :label="t('settings.language')" class="language" data-test="language"
      hide-details @update:model-value="changeLanguage" />
    <template v-if="!auth.desktop">
    <VTextField v-model="form.old" :label="t('settings.oldPassword')" type="password" autocomplete="current-password" data-test="old-password" />
    <VTextField v-model="form.next" :label="t('settings.newPassword')" type="password" autocomplete="new-password" data-test="new-password" />
    <VTextField v-model="form.repeat" :label="t('settings.repeatPassword')" type="password" autocomplete="new-password"
      data-test="repeat-password" />
    <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg">{{ error }}</VAlert>
    <div class="actions">
      <VBtn variant="text" :prepend-icon="mdiLogout" @click="logout">{{ t("nav.logout") }}</VBtn>
      <VSpacer />
      <VBtn color="primary" data-test="change-password" @click="change">{{ t("settings.changePassword") }}</VBtn>
    </div>
    </template>
  </div>
</template>

<style scoped>
.form { max-width: 440px; display: flex; flex-direction: column; gap: 4px; }
.language { margin-bottom: 20px; }
.actions { display: flex; align-items: center; margin-top: 8px; }
</style>

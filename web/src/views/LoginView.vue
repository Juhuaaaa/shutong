<script setup lang="ts">
import { mdiEye, mdiEyeOff } from "@mdi/js";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { ApiError } from "@/api/client";
import BrandMark from "@/components/BrandMark.vue";
import { useAuth } from "@/stores/auth";

const { t } = useI18n();
const auth = useAuth();
const route = useRoute();
const router = useRouter();
const password = ref("");
const visible = ref(false);
const error = ref("");
const busy = ref(false);
const firstUse = computed(() => auth.checked && !auth.configured);

onMounted(() => auth.refresh().catch((reason: ApiError) => (error.value = reason.detail)));

async function submit() {
  error.value = "";
  if (firstUse.value && password.value.length < 8) {
    error.value = t("login.tooShort");
    return;
  }
  busy.value = true;
  try {
    if (firstUse.value) await auth.setup(password.value);
    else await auth.login(password.value);
    const next = typeof route.query.next === "string" && route.query.next.startsWith("/") ? route.query.next : "/";
    await router.replace(next);
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.detail : String(reason);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="login">
    <VCard class="login-card pa-8">
      <div class="head">
        <BrandMark :size="48" />
        <div>
          <div class="name">{{ t("app.name") }}</div>
          <div class="st-muted text-body-2">{{ t("login.tagline") }}</div>
        </div>
      </div>
      <p class="hint">{{ firstUse ? t("login.firstUse") : t("login.prompt") }}</p>
      <form @submit.prevent="submit">
        <VTextField v-model="password" :type="visible ? 'text' : 'password'" :label="t('login.password')"
          :autocomplete="firstUse ? 'new-password' : 'current-password'" autofocus hide-details="auto"
          :append-inner-icon="visible ? mdiEyeOff : mdiEye" @click:append-inner="visible = !visible" />
        <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mt-4" rounded="lg">{{ error }}</VAlert>
        <VBtn type="submit" color="primary" block size="large" :loading="busy" class="mt-6">
          {{ firstUse ? t("login.setup") : t("login.submit") }}
        </VBtn>
      </form>
    </VCard>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px;
  background:
    radial-gradient(circle at 15% 20%, rgba(124, 77, 255, 0.16), transparent 40%),
    radial-gradient(circle at 85% 80%, rgba(0, 186, 209, 0.12), transparent 40%),
    rgb(var(--v-theme-background));
}
.login-card { width: 100%; max-width: 420px; }
.head { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; }
.name { font-size: 22px; font-weight: 700; }
.hint { margin: 0 0 16px; opacity: 0.8; }
</style>

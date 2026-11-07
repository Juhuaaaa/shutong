<script setup lang="ts">
import { mdiLanConnect } from "@mdi/js";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { settings as api } from "@/api";
import type { ApiError } from "@/api/client";
import { notify } from "@/composables/notify";
import { useSettingsForm } from "@/composables/useSettingsForm";

const { t } = useI18n();
const form = useSettingsForm(["network.proxy"]);
const proxyText = form.field<string>("network.proxy");
const testing = ref(false);
const result = ref<{ ok: boolean; text: string } | null>(null);
const proxy = computed(() => String(form.values["network.proxy"] ?? "").trim());
// Same shape the backend accepts (shutong.net.parse_proxy).
const bad = computed(() => Boolean(proxy.value) && !/^(https?|socks5h?):\/\/([^@/\s]+@)?[^:/@\s]+:\d{1,5}\/?$/i.test(proxy.value));

onMounted(() => form.load().catch((error: ApiError) => notify.error(error.detail)));

async function save() {
  try {
    notify.success((await form.save()) ? t("settings.saved") : t("settings.nothingChanged"));
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  }
}

async function test() {
  testing.value = true;
  result.value = null;
  try {
    const answer = await api.testProxy(proxy.value);
    result.value = answer.ok
      ? { ok: true, text: t("settings.proxyOk", { ms: answer.elapsed_ms }) }
      : { ok: false, text: t("settings.proxyFailed", { ms: answer.elapsed_ms, error: answer.error ?? "" }) };
  } catch (error) {
    result.value = { ok: false, text: (error as ApiError).detail ?? String(error) };
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="form">
    <VAlert type="info" variant="tonal" density="compact" rounded="lg">{{ t("settings.proxyUsage") }}</VAlert>
    <VTextField v-model="proxyText" :label="t('settings.proxy')" placeholder="http://192.168.1.10:7890"
      persistent-placeholder :hint="t('settings.proxyHint')" persistent-hint :error-messages="bad ? t('settings.proxyBad') : undefined"
      data-test="proxy" />
    <VAlert v-if="result" :type="result.ok ? 'success' : 'error'" variant="tonal" density="compact" rounded="lg">{{ result.text }}</VAlert>
    <div class="actions">
      <VBtn variant="tonal" :prepend-icon="mdiLanConnect" :loading="testing" :disabled="bad" data-test="test-proxy" @click="test">
        {{ t("settings.testConnection") }}
      </VBtn>
      <VBtn color="primary" :disabled="bad" data-test="save-network" @click="save">{{ t("common.save") }}</VBtn>
    </div>
  </div>
</template>

<style scoped>
.form { max-width: 600px; display: flex; flex-direction: column; gap: 12px; }
.form > .v-alert:first-child { margin-bottom: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>

<script setup lang="ts">
import { mdiCheck, mdiLanConnect } from "@mdi/js";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { aiCalls, settings as api, type AiCall } from "@/api";
import type { ApiError } from "@/api/client";
import { ask } from "@/composables/confirm";
import { shortTime } from "@/composables/format";
import { notify } from "@/composables/notify";
import { useSettingsForm } from "@/composables/useSettingsForm";
import SecretField from "./SecretField.vue";

const KEYS = ["ai.base_url", "ai.api_key", "ai.model", "ai.threshold", "ai.use_proxy"];
const { t } = useI18n();
const route = useRoute();
const form = useSettingsForm(KEYS);
const baseUrl = form.field<string>("ai.base_url");
const apiKey = form.field<string>("ai.api_key");
const model = form.field<string>("ai.model");
const useProxy = form.field<boolean>("ai.use_proxy");
const calls = ref<AiCall[]>([]);
const testing = ref(false);

onMounted(async () => {
  try {
    await form.load();
    calls.value = await aiCalls.recent(20);
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  }
});

function setThreshold(value: string) {
  const number = Number(value);
  form.values["ai.threshold"] = value === "" || Number.isNaN(number) ? form.values["ai.threshold"] : number;
}

async function save() {
  try {
    notify.success((await form.save()) ? t("settings.saved") : t("settings.nothingChanged"));
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  }
}

/** Saves without a word on success: the wizard moves on by itself. False when it could not be saved. */
async function commit(): Promise<boolean> {
  try {
    await form.save();
    return true;
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
    return false;
  }
}
defineExpose({ commit });

async function test() {
  testing.value = true;
  try {
    const result = await api.testAi();
    if (result.ok) notify.success(t("settings.aiOk"));
    else notify.error(result.error ?? "");
  } finally {
    testing.value = false;
  }
}

async function clear(key: string) {
  if (!(await ask(t("settings.clearSecretTitle"), t("settings.clearSecretText"), true))) return;
  try {
    await form.apply({ [key]: "" });
    notify.success(t("settings.saved"));
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  }
}
</script>

<template>
  <div class="form">
    <VAlert v-if="route.name !== 'welcome'" type="info" variant="tonal" density="compact" rounded="lg" data-test="ai-required">
      {{ t("settings.aiRequired") }}
    </VAlert>
    <VTextField v-model="baseUrl" :label="t('settings.aiUrl')" placeholder="https://api.deepseek.com"
      persistent-placeholder data-test="ai-url" />
    <SecretField v-model="apiKey" :label="t('settings.aiKey')" :is-set="!!form.secretSet['ai.api_key']"
      clear-test="clear-ai-key" data-test="ai-key" @clear="clear('ai.api_key')" />
    <div class="row">
      <VTextField v-model="model" :label="t('settings.aiModel')" data-test="ai-model" />
      <VTextField :model-value="String(form.values['ai.threshold'] ?? '')" :label="t('settings.aiThreshold')" type="number"
        min="0" max="1" step="0.01" data-test="ai-threshold" @update:model-value="setThreshold" />
    </div>
    <VSwitch v-model="useProxy" :label="t('settings.aiUseProxy')" :hint="t('settings.aiUseProxyHint')"
      persistent-hint data-test="ai-use-proxy" />
    <div class="hint">{{ t("settings.aiThresholdHint") }}</div>
    <div class="actions">
      <VBtn variant="tonal" :prepend-icon="mdiLanConnect" :loading="testing" @click="test">{{ t("settings.testConnection") }}</VBtn>
      <VBtn color="primary" data-test="save-ai" @click="save">{{ t("common.save") }}</VBtn>
    </div>
  </div>
  <div class="section-title">{{ t("settings.aiRecent") }}</div>
  <VTable density="comfortable" class="calls">
    <thead>
      <tr>
        <th>{{ t("history.time") }}</th><th>{{ t("settings.aiPurpose") }}</th><th>{{ t("settings.aiResult") }}</th>
        <th>{{ t("settings.aiAdopted") }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="call in calls" :key="call.id">
        <td class="nowrap">{{ shortTime(call.created_at) }}</td>
        <td class="nowrap">{{ call.purpose }}</td>
        <td class="result" :class="{ 'text-error': call.error }">{{ call.error ?? call.response_text ?? "" }}</td>
        <td><VIcon v-if="call.adopted" :icon="mdiCheck" color="success" size="18" /></td>
      </tr>
    </tbody>
  </VTable>
</template>

<style scoped>
.form { max-width: 600px; display: flex; flex-direction: column; gap: 8px; }
.form > .v-alert:first-child { margin-bottom: 12px; }
.row { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.hint { font-size: 12px; opacity: 0.7; }
.section-title { font-size: 13px; font-weight: 600; opacity: 0.7; margin: 28px 0 8px; }
.calls { background: transparent; }
.nowrap { white-space: nowrap; }
.result { max-width: 480px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 599px) {
  .row { grid-template-columns: minmax(0, 1fr); }
}
</style>

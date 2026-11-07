<script setup lang="ts">
import { onMounted } from "vue";
import { useI18n } from "vue-i18n";
import type { ApiError } from "@/api/client";
import { ask } from "@/composables/confirm";
import { notify } from "@/composables/notify";
import { useSettingsForm } from "@/composables/useSettingsForm";
import SecretField from "./SecretField.vue";

const { t } = useI18n();
const form = useSettingsForm(["bangumi.base_url", "bangumi.token"]);
const baseUrl = form.field<string>("bangumi.base_url");
const token = form.field<string>("bangumi.token");
onMounted(() => form.load().catch((error: ApiError) => notify.error(error.detail)));

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
    <VTextField v-model="baseUrl" :label="t('settings.bangumiUrl')" />
    <SecretField v-model="token" :label="t('settings.bangumiToken')"
      :hint="t('settings.bangumiTokenHint')" :is-set="!!form.secretSet['bangumi.token']" clear-test="clear-bangumi-token"
      @clear="clear('bangumi.token')" />
    <div class="actions"><VBtn color="primary" @click="save">{{ t("common.save") }}</VBtn></div>
  </div>
</template>

<style scoped>
.form { max-width: 600px; display: flex; flex-direction: column; gap: 8px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>

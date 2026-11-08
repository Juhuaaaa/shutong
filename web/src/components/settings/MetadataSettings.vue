<script setup lang="ts">
import { mdiArrowDown, mdiArrowUp } from "@mdi/js";
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { metadata, type MetadataSource } from "@/api";
import type { ApiError } from "@/api/client";
import { ask } from "@/composables/confirm";
import { notify } from "@/composables/notify";
import { useSettingsForm } from "@/composables/useSettingsForm";
import SecretField from "./SecretField.vue";

const { t, te } = useI18n();
const form = useSettingsForm(["metadata.sources", "bangumi.base_url", "bangumi.token"]);
const baseUrl = form.field<string>("bangumi.base_url");
const token = form.field<string>("bangumi.token");
const enabledNames = form.field<string[]>("metadata.sources");
/** Every source, the switched-on ones first in the order they are asked. */
const sources = ref<MetadataSource[]>([]);
const onCount = computed(() => sources.value.filter((source) => source.enabled).length);

async function load() {
  await form.load();
  const known = await metadata.sources();
  const on = (enabledNames.value ?? []).filter((name) => known.some((source) => source.name === name));
  sources.value = [
    ...on.map((name) => ({ ...known.find((source) => source.name === name)!, enabled: true })),
    ...known.filter((source) => !on.includes(source.name)).map((source) => ({ ...source, enabled: false })),
  ];
}
onMounted(() => load().catch((error: ApiError) => notify.error(error.detail)));

function sync() {
  enabledNames.value = sources.value.filter((source) => source.enabled).map((source) => source.name);
}

function toggle(index: number, on: boolean | null) {
  sources.value[index] = { ...sources.value[index], enabled: Boolean(on) };
  sync();
}

function move(index: number, step: number) {
  const next = [...sources.value];
  [next[index], next[index + step]] = [next[index + step], next[index]];
  sources.value = next;
  sync();
}

function note(name: string): string {
  return te(`settings.sourceNotes.${name}`) ? t(`settings.sourceNotes.${name}`) : "";
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
    <div class="text-subtitle-2">{{ t("settings.sourcesTitle") }}</div>
    <div class="st-muted text-body-2">{{ t("settings.sourcesHint") }}</div>
    <div class="sources" data-test="sources">
      <div v-for="(source, index) in sources" :key="source.name" class="source" :data-test="`source-${source.name}`">
        <VSwitch :model-value="source.enabled" color="primary" density="compact" hide-details inset
          :disabled="source.enabled && onCount === 1" :aria-label="source.label" :data-test="`source-switch-${source.name}`"
          @update:model-value="toggle(index, $event)" />
        <div class="source-text">
          <strong>{{ source.label }}</strong>
          <span v-if="note(source.name)" class="st-muted text-caption">{{ note(source.name) }}</span>
        </div>
        <VBtn :icon="mdiArrowUp" size="small" variant="text" :disabled="index === 0" :aria-label="t('settings.moveUp')"
          :data-test="`source-up-${source.name}`" @click="move(index, -1)" />
        <VBtn :icon="mdiArrowDown" size="small" variant="text" :disabled="index === sources.length - 1"
          :aria-label="t('settings.moveDown')" :data-test="`source-down-${source.name}`" @click="move(index, 1)" />
      </div>
    </div>
    <div class="text-subtitle-2 mt-4">Bangumi</div>
    <VTextField v-model="baseUrl" :label="t('settings.bangumiUrl')" />
    <SecretField v-model="token" :label="t('settings.bangumiToken')"
      :hint="t('settings.bangumiTokenHint')" :is-set="!!form.secretSet['bangumi.token']" clear-test="clear-bangumi-token"
      @clear="clear('bangumi.token')" />
    <div class="actions"><VBtn color="primary" data-test="save-metadata" @click="save">{{ t("common.save") }}</VBtn></div>
  </div>
</template>

<style scoped>
.form { max-width: 600px; display: flex; flex-direction: column; gap: 8px; }
.sources { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.source {
  display: flex; align-items: center; gap: 8px; padding: 4px 8px; border-radius: 12px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.source-text { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>

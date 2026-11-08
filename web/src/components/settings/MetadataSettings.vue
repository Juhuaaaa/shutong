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
const form = useSettingsForm(["metadata.sources", "metadata.translate_summaries", "bangumi.base_url",
  "bangumi.image_base_url", "bangumi.token"]);
const imageUrl = form.field<string>("bangumi.image_base_url");
const translate = form.field<boolean>("metadata.translate_summaries");
const baseUrl = form.field<string>("bangumi.base_url");
const token = form.field<string>("bangumi.token");
const enabledNames = form.field<string[]>("metadata.sources");
/** Every source, the switched-on ones first in the order they are asked. */
const sources = ref<MetadataSource[]>([]);
const refused = ref(0);
const onCount = computed(() => sources.value.filter((source) => source.enabled).length);

async function load() {
  await form.load();
  // What the server really asks, in its order: a stored name it no longer knows is not shown as switched on.
  sources.value = await metadata.sources();
}
onMounted(() => load().catch((error: ApiError) => notify.error(error.detail)));

function sync() {
  enabledNames.value = sources.value.filter((source) => source.enabled).map((source) => source.name);
}

function toggle(index: number, on: boolean | null) {
  if (!on && onCount.value === 1 && sources.value[index].enabled) {
    // At least one source has to be asked: the switch springs back on (a new key redraws it) rather than being
    // greyed out, which looked like off.
    refused.value += 1;
    notify.error(t("settings.keepOneSource"));
    return;
  }
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

// Known addresses to pick from; any other can still be typed in.
const API_ADDRESSES = ["https://api.bgm.tv", "https://bgmapi.anibt.net"];
const IMAGE_ADDRESSES = ["https://lain.bgm.tv", "https://bgmimg.anibt.net"];
const OFFICIAL = new Set(["https://api.bgm.tv", "https://lain.bgm.tv"]);
const TOKEN_PAGE = "https://next.bgm.tv/demo/access-token";

function addressProps(address: string) {
  return { title: address, subtitle: t(OFFICIAL.has(address) ? "settings.addressOfficial" : "settings.addressMirror") };
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
      <div v-for="(source, index) in sources" :key="source.name" class="source" :class="{ off: !source.enabled }"
        :data-test="`source-${source.name}`">
        <VSwitch :key="`${source.name}-${refused}`" :model-value="source.enabled" color="primary" hide-details inset class="flex-grow-0"
          :aria-label="source.label" :data-test="`source-switch-${source.name}`" @update:model-value="toggle(index, $event)" />
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
    <VSwitch v-model="translate" :label="t('settings.translateSummaries')" :hint="t('settings.translateSummariesHint')"
      persistent-hint class="mt-2" data-test="translate-summaries" />
    <div class="text-subtitle-2 mt-4">Bangumi</div>
    <div class="addresses" data-test="bangumi-addresses">
      <VCombobox v-model="baseUrl" :items="API_ADDRESSES" :item-props="addressProps" :label="t('settings.bangumiUrl')"
        :hint="t('settings.bangumiUrlHint')" persistent-hint data-test="bangumi-url" />
      <VCombobox v-model="imageUrl" :items="IMAGE_ADDRESSES" :item-props="addressProps" :label="t('settings.bangumiImageUrl')"
        :hint="t('settings.bangumiImageUrlHint')" persistent-hint placeholder="https://lain.bgm.tv" persistent-placeholder
        clearable data-test="bangumi-image-url" @click:clear="imageUrl = ''" />
    </div>
    <SecretField v-model="token" :label="t('settings.bangumiToken')"
      :hint="t('settings.bangumiTokenHint')" :is-set="!!form.secretSet['bangumi.token']" clear-test="clear-bangumi-token"
      @clear="clear('bangumi.token')" />
    <a :href="TOKEN_PAGE" target="_blank" rel="noopener noreferrer" class="token-link text-caption" data-test="bangumi-token-link">
      {{ t("settings.bangumiTokenApply") }}
    </a>
    <div class="actions"><VBtn color="primary" data-test="save-metadata" @click="save">{{ t("common.save") }}</VBtn></div>
  </div>
</template>

<style scoped>
.addresses { display: flex; flex-direction: column; gap: 8px; }
.token-link { color: rgb(var(--v-theme-primary)); margin: -4px 0 0 16px; }
.form { max-width: 600px; display: flex; flex-direction: column; gap: 8px; }
.sources { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.source {
  display: flex; align-items: center; gap: 8px; padding: 4px 8px; border-radius: 12px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.source-text { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.source.off .source-text { opacity: 0.55; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>

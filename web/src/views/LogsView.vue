<script setup lang="ts">
import { mdiDownload, mdiMagnify, mdiPause, mdiPlay } from "@mdi/js";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { logs as api, settings as settingsApi, type LogPage } from "@/api";
import { ApiError } from "@/api/client";
import { notify } from "@/composables/notify";

type Line = LogPage["entries"][number];
const KEEP = 1000; // lines kept on screen; the file has everything
const EVERY = 2000;
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;

const { t } = useI18n();
const lines = ref<Line[]>([]);
const level = ref<string>("");
const query = ref("");
const following = ref(true);
const recordLevel = ref("INFO");
const box = ref<HTMLElement | null>(null);
let after = 0;
let timer: ReturnType<typeof setInterval> | undefined;
let loading = false;
let typing: ReturnType<typeof setTimeout> | undefined;
let generation = 0; // bumped by every filter change; answers to older requests are dropped

const levelItems = computed(() => LEVELS.map((value) => ({ title: t(`logs.levels.${value}`), value })));

async function fetchMore(reset = false) {
  if (reset) {
    generation += 1;
    after = 0;
    lines.value = [];
  } else if (loading) {
    return; // a poll is already on its way
  }
  const mine = generation;
  loading = true;
  try {
    const page = await api.read({ after, level: level.value || undefined, q: query.value.trim() || undefined });
    if (mine !== generation) return;
    after = page.last_seq;
    if (page.entries.length) {
      lines.value = [...lines.value, ...page.entries].slice(-KEEP);
      if (following.value) {
        await nextTick();
        box.value?.scrollTo({ top: box.value.scrollHeight });
      }
    }
  } catch (error) {
    if (reset) notify.error(error instanceof ApiError ? error.detail : String(error));
  } finally {
    if (mine === generation) loading = false;
  }
}

function start() {
  clearInterval(timer);
  timer = setInterval(() => following.value && !document.hidden && fetchMore(), EVERY);
}

onMounted(async () => {
  await fetchMore(true);
  start();
  try {
    recordLevel.value = String((await settingsApi.get())["log.level"] ?? "INFO");
  } catch {
    /* the selector keeps its default */
  }
});
onUnmounted(() => {
  clearInterval(timer);
  clearTimeout(typing);
});

watch(level, () => fetchMore(true));
watch(query, () => {
  clearTimeout(typing);
  typing = setTimeout(() => fetchMore(true), 300);
});

async function setRecordLevel(value: string) {
  try {
    await settingsApi.update({ "log.level": value });
    recordLevel.value = value;
  } catch (error) {
    notify.error(error instanceof ApiError ? error.detail : String(error));
  }
}

function time(iso: string) {
  return iso.slice(5, 19).replace("T", " ");
}
</script>

<template>
  <div class="st-page logs-page">
    <div class="toolbar">
      <h1 class="st-page-title">{{ t("nav.logs") }}</h1>
      <VSpacer />
      <VSelect :model-value="recordLevel" :items="levelItems" :label="t('logs.recordLevel')" density="compact" hide-details
        class="record" @update:model-value="setRecordLevel" />
      <VBtn variant="tonal" :prepend-icon="mdiDownload" :href="api.downloadUrl" data-test="download">{{ t("logs.download") }}</VBtn>
    </div>
    <VCard class="pa-4 body">
      <div class="filters">
        <VChipGroup v-model="level" mandatory selected-class="text-primary" class="levels">
          <VChip value="" variant="tonal" data-test="level-all">{{ t("logs.all") }}</VChip>
          <VChip v-for="name in LEVELS.slice(1)" :key="name" :value="name" variant="tonal" :data-test="`level-${name}`">
            {{ t(`logs.levels.${name}`) }}+
          </VChip>
        </VChipGroup>
        <VTextField v-model="query" density="compact" hide-details clearable :prepend-inner-icon="mdiMagnify"
          :placeholder="t('logs.search')" class="search" />
        <VBtn variant="text" :prepend-icon="following ? mdiPause : mdiPlay" data-test="follow" @click="following = !following">
          {{ following ? t("logs.follow") : t("logs.paused") }}
        </VBtn>
      </div>
      <div ref="box" class="lines" role="log" aria-live="polite">
        <div v-for="line in lines" :key="line.seq" class="line" :class="`level-${line.level.toLowerCase()}`" data-test="log-line">
          <span class="at">{{ time(line.at) }}</span>
          <span class="level">{{ line.level }}</span>
          <span class="message">{{ line.message }}</span>
        </div>
        <div v-if="!lines.length" class="st-muted pa-4">{{ t("logs.empty") }}</div>
      </div>
      <div class="st-muted text-caption mt-2">{{ t("logs.shown", { count: lines.length }) }}</div>
    </VCard>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.record { max-width: 160px; }
.filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.search { max-width: 280px; min-width: 180px; }
.lines {
  height: calc(100vh - 290px); min-height: 320px; overflow: auto; border-radius: 10px; padding: 10px 12px;
  background: rgba(var(--v-theme-on-surface), 0.04);
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12.5px; line-height: 1.6;
}
.line { display: flex; gap: 10px; white-space: pre-wrap; word-break: break-all; }
.at { opacity: 0.55; flex: none; }
.level { width: 60px; flex: none; font-weight: 600; }
.message { flex: 1; min-width: 0; }
.level-debug { opacity: 0.6; }
.level-info .level { color: rgb(var(--v-theme-info)); }
.level-warning .level, .level-warning .message { color: rgb(var(--v-theme-warning)); }
.level-error .level, .level-error .message { color: rgb(var(--v-theme-error)); }
@media (max-width: 599px) {
  .lines { height: calc(100vh - 340px); font-size: 11.5px; }
  .line { flex-wrap: wrap; gap: 0 8px; }
  .message { flex-basis: 100%; }
}
</style>

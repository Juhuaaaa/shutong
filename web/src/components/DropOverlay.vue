<script setup lang="ts">
import { mdiBookOpenVariant, mdiNotebookOutline } from "@mdi/js";
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { desktop, type Library } from "@/api";
import { ApiError } from "@/api/client";
import { bridge } from "@/composables/desktop";
import { dropAttention, dropSummary } from "@/composables/format";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

const { t } = useI18n();
const router = useRouter();
const jobs = useJobs();
const libraries = useLibraries();
const visible = ref(false);
const over = ref<number | null>(null);
let depth = 0; // dragenter and dragleave also fire for everything under the pointer

const carriesFiles = (event: DragEvent) => event.dataTransfer?.types.includes("Files") ?? false;

function entered(event: DragEvent) {
  if (!carriesFiles(event)) return;
  event.preventDefault();
  depth += 1;
  visible.value = true;
}

function left() {
  depth = Math.max(0, depth - 1);
  if (depth === 0) close();
}

function hovering(event: DragEvent) {
  event.preventDefault(); // otherwise the window opens the dropped file itself
}

function close() {
  depth = 0;
  visible.value = false;
  over.value = null;
}

function dropped(event: DragEvent) {
  event.preventDefault();
  close();
}

function reason(item: { path: string; reason: string }) {
  const name = item.path.split(/[/\\]/).pop();
  return `${name}（${t(`desktop.drop.reasons.${item.reason}`)}）`;
}

async function drop(event: DragEvent, library: Library) {
  event.preventDefault();
  event.stopPropagation();
  const files = [...(event.dataTransfer?.files ?? [])];
  close();
  const paths = bridge()?.pathsFor(files) ?? [];
  if (!paths.length) return;
  try {
    const result = await desktop.scanPaths(library.id, paths);
    if (result.rejected.length) notify.error(t("desktop.drop.rejected"));
    if (result.skipped.length) {
      notify.error(t("desktop.drop.skipped", { count: result.skipped.length, first: reason(result.skipped[0]) }));
    }
    if (result.job_id == null) {
      if (!result.rejected.length && !result.skipped.length) notify.error(t("desktop.drop.nothing"));
      return;
    }
    const job = await jobs.submit(Promise.resolve({ job_id: result.job_id }), t("jobs.scanOf", { name: library.name }));
    const counts = (job.result as { counts?: Record<string, number> }).counts ?? {};
    (dropAttention(counts) ? notify.warning : notify.success)(dropSummary(counts));
    libraries.refresh().catch(() => {});
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      notify.error(t("desktop.drop.needAi"));
      await router.push({ name: "settings", params: { tab: "ai" } });
    } else {
      notify.error(error instanceof ApiError ? error.detail : String(error));
    }
  }
}

onMounted(() => {
  window.addEventListener("dragenter", entered);
  window.addEventListener("dragleave", left);
  window.addEventListener("dragover", hovering);
  window.addEventListener("drop", dropped);
});
onUnmounted(() => {
  window.removeEventListener("dragenter", entered);
  window.removeEventListener("dragleave", left);
  window.removeEventListener("dragover", hovering);
  window.removeEventListener("drop", dropped);
});
</script>

<template>
  <div v-if="visible" class="overlay" data-test="drop-overlay">
    <div class="text-h6 title">{{ t("desktop.drop.title") }}</div>
    <div class="targets">
      <div v-for="library in libraries.list" :key="library.id" class="target" :class="{ over: over === library.id }"
        :data-test="`drop-${library.id}`" @dragenter="over = library.id" @dragover.prevent="over = library.id"
        @drop="drop($event, library)">
        <VIcon :icon="library.kind === 'manga' ? mdiBookOpenVariant : mdiNotebookOutline" size="48" />
        <div class="text-subtitle-1 font-weight-medium mt-3">{{ library.name }}</div>
        <div class="text-caption st-muted">{{ t(`desktop.drop.${library.kind}`) }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay { position: fixed; inset: 0; z-index: 3000; display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 24px; background: rgba(var(--v-theme-background), 0.94); }
.title { margin-bottom: 24px; }
.targets { display: flex; flex-wrap: wrap; justify-content: center; gap: 24px; }
.target { width: 260px; height: 220px; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
  border: 2px dashed rgba(var(--v-theme-on-surface), 0.3); border-radius: 16px; background: rgb(var(--v-theme-surface)); }
.target * { pointer-events: none; }
.target.over { border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.08); }
</style>

<script setup lang="ts">
import { mdiBookOpenVariant, mdiCheckCircleOutline, mdiFileUploadOutline, mdiFolderUploadOutline, mdiNotebookOutline, mdiTrayArrowUp } from "@mdi/js";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as api, type Library } from "@/api";
import { ApiError } from "@/api/client";
import { scanSummary } from "@/composables/format";
import { notify } from "@/composables/notify";
import { filesFromDrop, filesFromInput, uploadAll, type PendingFile } from "@/composables/upload";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

const { t } = useI18n();
const libraries = useLibraries();
const jobs = useJobs();
const targetId = ref<number | null>(null);
const dragging = ref(false);
const phase = ref<"idle" | "uploading" | "organizing">("idle");
const progress = ref({ done: 0, total: 0 });
const result = ref<{ library: Library; saved: number; skipped: number; counts: Record<string, number> } | null>(null);
const filePicker = ref<HTMLInputElement | null>(null);
const folderPicker = ref<HTMLInputElement | null>(null);

const target = computed(() => libraries.list.find((library) => library.id === targetId.value) ?? null);
const busy = computed(() => phase.value !== "idle");
const ready = computed(() => target.value !== null && target.value.available && !busy.value);

onMounted(() => libraries.refresh().catch(() => {}));
watch(() => libraries.current, (current) => {
  if (targetId.value === null && current) targetId.value = current.id;
}, { immediate: true });

function failed(error: unknown) {
  notify.error(error instanceof ApiError ? error.detail : String(error));
}

async function start(files: PendingFile[]) {
  const library = target.value;
  if (!files.length || !library || !ready.value) return;
  result.value = null;
  phase.value = "uploading";
  progress.value = { done: 0, total: files.length };
  try {
    const summary = await uploadAll(files, (file) => api.upload(library.id, file.file, file.path),
      (done, total) => (progress.value = { done, total }));
    if (summary.failed.length) {
      notify.error(t("upload.failed", { count: summary.failed.length, first: `${summary.failed[0].path}：${summary.failed[0].error}` }));
    }
    let counts: Record<string, number> = {};
    if (summary.saved) {
      phase.value = "organizing";
      const job = await jobs.submit(api.scan(library.id), t("jobs.scanOf", { name: library.name }));
      counts = (job.result as { counts?: Record<string, number> }).counts ?? {};
      await libraries.refresh().catch(() => {});
    }
    result.value = { library, saved: summary.saved, skipped: summary.skipped, counts };
  } catch (error) {
    failed(error);
  } finally {
    phase.value = "idle";
  }
}

async function onDrop(event: DragEvent) {
  dragging.value = false;
  if (event.dataTransfer && ready.value) await start(await filesFromDrop(event.dataTransfer));
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files) start(filesFromInput(input.files));
  input.value = "";
}
</script>

<template>
  <div class="st-page">
    <h1 class="st-page-title">{{ t("nav.upload") }}</h1>

    <div class="section-title">{{ t("upload.pickLibrary") }}</div>
    <VCard v-if="libraries.loaded && !libraries.list.length" class="pa-6 text-center st-muted">
      {{ t("library.empty") }}
    </VCard>
    <div class="targets">
      <VCard v-for="library in libraries.list" :key="library.id" class="target" :class="{ chosen: library.id === targetId }"
        :disabled="busy || !library.available" role="radio" :aria-checked="library.id === targetId" tabindex="0"
        data-test="target" @click="targetId = library.id" @keydown.enter.prevent="targetId = library.id">
        <VAvatar :color="library.kind === 'manga' ? 'primary' : 'info'" variant="tonal" rounded="lg" size="40">
          <VIcon :icon="library.kind === 'manga' ? mdiBookOpenVariant : mdiNotebookOutline" />
        </VAvatar>
        <div class="target-text">
          <div class="font-weight-bold">{{ library.name }}</div>
          <div class="st-muted text-caption path">{{ library.library_dir }}</div>
        </div>
        <VChip v-if="!library.available" size="x-small" color="error" variant="tonal">{{ t("library.unavailable") }}</VChip>
      </VCard>
    </div>

    <VCard class="drop" :class="{ dragging, disabled: !ready }" data-test="drop"
      @dragover.prevent="ready && (dragging = true)" @dragleave="dragging = false" @drop.prevent="onDrop">
      <template v-if="phase === 'idle'">
        <VIcon :icon="mdiTrayArrowUp" size="48" color="primary" />
        <div class="text-subtitle-1 font-weight-medium mt-3">{{ t("upload.dropHere") }}</div>
        <div v-if="target" class="st-muted text-body-2 mt-1">
          {{ target.source_dir ? t("upload.flow", { source: target.source_dir, library: target.name })
            : t("upload.flowUploadOnly", { library: target.name }) }}
        </div>
        <div class="buttons">
          <VBtn color="primary" :prepend-icon="mdiFileUploadOutline" :disabled="!ready" data-test="pick-files"
            @click="filePicker?.click()">
            {{ t("upload.pickFiles") }}
          </VBtn>
          <VBtn variant="tonal" color="primary" :prepend-icon="mdiFolderUploadOutline" :disabled="!ready" data-test="pick-folder"
            @click="folderPicker?.click()">
            {{ t("upload.pickFolder") }}
          </VBtn>
        </div>
      </template>
      <div v-else class="working">
        <div class="text-subtitle-1 font-weight-medium mb-3">
          {{ phase === "uploading" ? t("upload.uploading", progress) : t("upload.organizing", { name: target?.name }) }}
        </div>
        <VProgressLinear :model-value="phase === 'uploading' ? Math.round((progress.done / Math.max(progress.total, 1)) * 100) : undefined"
          :indeterminate="phase === 'organizing'" color="primary" rounded height="8" />
      </div>
      <input ref="filePicker" type="file" multiple class="hidden" data-test="file-input" @change="onPick">
      <input ref="folderPicker" type="file" webkitdirectory multiple class="hidden" @change="onPick">
    </VCard>

    <VAlert v-if="result" type="success" variant="tonal" rounded="lg" :icon="mdiCheckCircleOutline" data-test="result">
      <div>{{ t("upload.done", { saved: result.saved, skipped: result.skipped, name: result.library.name }) }}</div>
      <div v-if="result.saved">{{ scanSummary(result.counts) }}</div>
      <div v-if="result.counts.needs_review" class="mt-2">
        <VBtn size="small" variant="tonal" :to="{ name: 'review' }">{{ t("upload.toReview") }}</VBtn>
      </div>
    </VAlert>
  </div>
</template>

<style scoped>
.section-title { font-size: 13px; font-weight: 600; opacity: 0.7; margin-bottom: 10px; }
.targets { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); gap: 12px; margin-bottom: 20px; }
.target { display: flex; align-items: center; gap: 12px; padding: 14px 16px; cursor: pointer;
  outline: 2px solid transparent; transition: outline-color 0.15s; }
.target.chosen { outline-color: rgb(var(--v-theme-primary)); }
.target-text { min-width: 0; flex: 1; }
.path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drop { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
  min-height: 280px; padding: 32px 20px; margin-bottom: 20px; border: 2px dashed rgba(var(--v-border-color), 0.25);
  transition: border-color 0.15s, background-color 0.15s; }
.drop.dragging { border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.05); }
.drop.disabled { opacity: 0.7; }
.buttons { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; margin-top: 20px; }
.working { width: min(100%, 420px); }
.hidden { display: none; }
</style>

<script setup lang="ts">
import {
  mdiArrowDown, mdiBookOpenVariant, mdiChevronDown, mdiCloudSyncOutline, mdiChevronUp, mdiFolderOpenOutline, mdiFolderOutline, mdiNotebookOutline, mdiRefresh, mdiTrayArrowUp,
} from "@mdi/js";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { items, libraries as api, servers as serverApi, type Library, type LibraryPatch, type Run, type Server } from "@/api";
import { ApiError } from "@/api/client";
import { ask } from "@/composables/confirm";
import { shortTime } from "@/composables/format";
import { bridge } from "@/composables/desktop";
import { notify } from "@/composables/notify";
import { useAuth } from "@/stores/auth";
import { useJobs } from "@/stores/jobs";

const props = withDefaults(defineProps<{
  library: Library | null; // null: a new library
  counts?: Record<string, number>;
  lastRun?: Run | null;
  servers?: Server[];
  scanning?: boolean;
  expanded?: boolean;
  previewDelay?: number;
}>(), { counts: () => ({}), lastRun: null, servers: () => [], scanning: false, expanded: false, previewDelay: 300 });
const emit = defineEmits<{ saved: [library: Library]; cancel: []; scan: [] }>();
const { t } = useI18n();
const auth = useAuth();
const templateVars = computed(() => `{series} {title}${form.kind === "manga" ? " {edition}" : ""} {volume} {year} {bgm} {ext}`);

const open = ref(props.expanded || props.library === null);

const initial = {
  name: props.library?.name ?? "",
  kind: props.library?.kind ?? "manga",
  source_dir: props.library?.source_dir ?? "",
  library_dir: props.library?.library_dir ?? "",
  naming_template: props.library?.naming_template ?? "",
  source_policy: props.library?.source_policy ?? "keep",
  archive_dir: props.library?.archive_dir ?? "",
  pdf_to_cbz: props.library?.pdf_to_cbz ?? true,
  include_edition: props.library?.include_edition ?? true,
  overwrite_policy: props.library?.overwrite_policy ?? "never",
  rename_files: props.library?.rename_files ?? true,
  server_id: props.library?.server_id ?? null,
  server_library_id: props.library?.server_library_id ?? null,
  watch: props.library?.watch ?? false,
};
const form = reactive({ ...initial });
const serverLibraries = ref<{ title: string; value: string }[]>([]);
const serverError = ref("");
const templateError = ref("");
const examples = ref<{ source: string; target: string }[]>([]);
const saveError = ref("");
const saving = ref(false);

// No source dir: uploads wait under the data dir, so there is nothing to keep them in.
const uploadOnly = computed(() => !form.source_dir.trim());
const policies = computed(() => (["keep", "archive", "delete"] as const)
  .filter((value) => !(uploadOnly.value && value === "keep"))
  .map((value) => ({ value, title: t(`library.policy.${value}`) })));
const overwrites = computed(() => (["never", "always", "larger", "newer"] as const)
  .map((value) => ({ value, title: t(`library.overwrite.${value}`) })));
const archiveMissing = computed(() => form.source_policy === "archive" && !form.archive_dir.trim());
const missing = computed(() => !form.name.trim() || !form.library_dir.trim());
const dirty = computed(() => props.library === null || Object.keys(changes()).length > 0);
const canSave = computed(() => dirty.value && !missing.value && !archiveMissing.value && !templateError.value && !saving.value);
const server = computed(() => props.servers.find((entry) => entry.id === props.library?.server_id));

onMounted(() => {
  if (form.server_id !== null) loadServerLibraries(form.server_id);
});

async function loadServerLibraries(id: number | null) {
  serverLibraries.value = [];
  serverError.value = "";
  if (id === null) return;
  try {
    const result = await serverApi.test(id);
    if (result.ok) serverLibraries.value = result.libraries.map((entry) => ({ title: `${entry.name} (${entry.id})`, value: entry.id }));
    else serverError.value = result.error ?? "";
  } catch (error) {
    serverError.value = error instanceof ApiError ? error.detail : String(error);
  }
}

function pickServer(id: number | null) {
  form.server_id = id;
  form.server_library_id = null;
  loadServerLibraries(id);
}

async function pickLibraryDir() {
  const picked = await bridge()?.pickFolder(form.library_dir || undefined);
  if (picked) form.library_dir = picked;
}

watch(uploadOnly, (only) => {
  if (!only || auth.desktop) return;
  if (form.source_policy === "keep") form.source_policy = "delete";
  form.watch = false;
});

let timer: ReturnType<typeof setTimeout> | undefined;
watch(
  () => form.naming_template,
  (template) => {
    clearTimeout(timer);
    templateError.value = "";
    examples.value = [];
    if (!props.library || !template.trim()) return;
    timer = setTimeout(async () => {
      try {
        examples.value = (await api.templatePreview(props.library!.id, template)).examples;
      } catch (error) {
        if (form.naming_template === template) templateError.value = (error as ApiError).detail ?? String(error);
      }
    }, props.previewDelay);
  },
);

async function refreshMetadata() {
  const library = props.library;
  if (!library || !(await ask(t("library.refreshTitle", { name: library.name }), t("library.refreshText")))) return;
  try {
    const job = await useJobs().submit(items.refreshMetadata({ library_id: library.id }), t("jobs.kind.refresh_metadata"));
    const result = job.result as Record<string, number>;
    const counts = { refreshed: result.refreshed ?? 0, unchanged: result.unchanged ?? 0, skipped: result.skipped ?? 0, failed: result.failed ?? 0 };
    if (counts.failed) notify.warning(t("history.refreshedPartly", counts));
    else notify.success(t("history.refreshed", counts));
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  }
}

function changes(): LibraryPatch {
  const patch: Record<string, unknown> = {};
  for (const key of Object.keys(initial) as (keyof typeof initial)[]) {
    if (key === "kind") continue;
    if (form[key] !== initial[key]) patch[key] = form[key] === "" && key === "archive_dir" ? null : form[key];
  }
  return patch as LibraryPatch;
}

async function save() {
  saving.value = true;
  saveError.value = "";
  try {
    const saved = props.library
      ? await api.update(props.library.id, changes())
      : await api.create({ ...form, kind: form.kind as "manga" | "novel", archive_dir: form.archive_dir || null,
          source_policy: form.source_policy as "keep" | "archive" | "delete",
          overwrite_policy: form.overwrite_policy as "never" | "always" | "larger" | "newer" });
    Object.assign(initial, { ...form });
    emit("saved", saved);
  } catch (error) {
    saveError.value = (error as ApiError).detail ?? String(error);
  } finally {
    saving.value = false;
  }
}

function cancel() {
  Object.assign(form, initial);
  if (props.library === null) emit("cancel");
  else open.value = false;
}
</script>

<template>
  <VCard class="library-card" data-test="library-card">
      <div class="head">
        <VAvatar :color="form.kind === 'manga' ? 'primary' : 'info'" variant="tonal" rounded="lg" size="44">
          <VIcon :icon="form.kind === 'manga' ? mdiBookOpenVariant : mdiNotebookOutline" />
        </VAvatar>
        <div class="title">
          <div class="text-subtitle-1 font-weight-bold">{{ library?.name || t("library.create") }}</div>
          <div class="st-muted text-caption">
            {{ t(`library.${form.kind}`) }}
            <template v-if="library"> · {{ t(`library.policyShort.${library.source_policy}`) }}</template>
            <template v-if="server"> · {{ server.name }}</template>
            <template v-if="library?.watch"> · {{ t("library.watching") }}</template>
          </div>
        </div>
        <VSpacer />
        <VChip v-if="library && !library.available" size="small" color="error" variant="tonal">{{ t("library.unavailable") }}</VChip>
        <VBtn v-if="library" icon variant="text" size="small" :title="open ? t('library.collapse') : t('library.expand')"
          data-test="toggle" @click="open = !open">
          <VIcon :icon="open ? mdiChevronUp : mdiChevronDown" />
        </VBtn>
      </div>

      <template v-if="library && !open">
        <div class="paths">
          <template v-if="!auth.desktop">
            <div v-if="library.source_dir" class="path" :title="library.source_dir">
              <VIcon :icon="mdiFolderOutline" size="16" /> <span>{{ library.source_dir }}</span>
            </div>
            <div v-else class="path st-muted"><VIcon :icon="mdiTrayArrowUp" size="16" /> <span>{{ t("library.uploadOnly") }}</span></div>
            <VIcon :icon="mdiArrowDown" size="14" class="st-muted arrow" />
          </template>
          <div class="path" :title="library.library_dir"><VIcon :icon="mdiFolderOutline" size="16" /> <span>{{ library.library_dir }}</span></div>
        </div>
        <div class="foot">
          <span class="st-muted text-caption foot-text">
            {{ t("library.counts", { review: counts.needs_review ?? 0, failed: counts.failed ?? 0 }) }}
            · {{ lastRun ? t(auth.desktop ? "desktop.lastRun" : "library.lastScan", { time: shortTime(lastRun.finished_at ?? lastRun.started_at) }) : t(auth.desktop ? "desktop.neverRun" : "library.neverScanned") }}
          </span>
          <VBtn variant="text" size="small" :prepend-icon="mdiCloudSyncOutline" :disabled="!library.available || scanning"
            data-test="refresh-metadata" @click="refreshMetadata">
            {{ t("library.refreshMetadata") }}
          </VBtn>
          <VBtn v-if="auth.desktop" variant="tonal" color="primary" size="small" :prepend-icon="mdiFolderOpenOutline"
            data-test="open-folder" @click="bridge()?.openPath(library!.library_dir)">
            {{ t("desktop.openFolder") }}
          </VBtn>
          <VBtn v-else variant="tonal" color="primary" size="small" :prepend-icon="mdiRefresh" :loading="scanning"
            :disabled="!library.available || scanning" data-test="scan" @click="emit('scan')">
            {{ t("library.scan") }}
          </VBtn>
        </div>
      </template>

      <div v-if="open" class="form">
        <section>
          <div class="section-title">{{ t("library.paths") }}</div>
          <div class="grid">
            <VTextField v-model="form.name" :label="t('library.name')" data-test="name" />
            <VSelect v-if="!library" v-model="form.kind" :label="t('library.kind')"
              :items="[{ title: t('library.manga'), value: 'manga' }, { title: t('library.novel'), value: 'novel' }]" />
            <VTextField v-if="!auth.desktop" v-model="form.source_dir" :label="t('library.sourceDir')" placeholder="/media/downloads/manga"
              :hint="t('library.sourceDirHint')" persistent-hint data-test="source-dir" />
            <VTextField v-model="form.library_dir" :label="t('library.libraryDir')" placeholder="/media/manga"
              data-test="library-dir" :append-inner-icon="auth.desktop ? mdiFolderOpenOutline : undefined"
              @click:append-inner="pickLibraryDir" />
          </div>
        </section>
        <section>
          <div class="section-title">{{ t("library.organize") }}</div>
          <div class="grid">
            <VSelect v-if="!auth.desktop" v-model="form.source_policy" :label="t('library.policyLabel')" :items="policies" />
            <VSelect v-model="form.overwrite_policy" :label="t('library.overwriteLabel')" :items="overwrites"
              :hint="t(`library.overwriteHint.${form.overwrite_policy}`)" persistent-hint data-test="overwrite" />
            <VTextField v-if="form.source_policy === 'archive' && !auth.desktop" v-model="form.archive_dir" :label="t('library.archiveDir')"
              :error-messages="archiveMissing ? t('library.archiveMissing') : undefined" />
          </div>
          <div class="grid switches">
            <VSwitch v-if="!auth.desktop" v-model="form.watch" :label="t('library.watch')" :disabled="uploadOnly"
              :hint="uploadOnly ? t('library.watchNeedsSource') : t('library.watchHint')" persistent-hint data-test="watch" />
            <VSwitch v-if="form.kind === 'manga'" v-model="form.include_edition" :label="t('library.includeEdition')" :hint="t('library.includeEditionHint')"
              persistent-hint data-test="include-edition" />
            <VSwitch v-if="form.kind === 'manga'" v-model="form.pdf_to_cbz" :label="t('library.pdfToCbz')"
              :hint="t('library.pdfToCbzHint')" persistent-hint />
          </div>
        </section>
        <section>
          <div class="section-title">{{ t("library.naming") }}</div>
          <VSwitch v-model="form.rename_files" :label="t('library.renameFiles')" :hint="t('library.renameFilesHint')"
            persistent-hint class="mb-4" data-test="rename-files" />
          <VTextField v-model="form.naming_template" :label="t('library.template')" :placeholder="t('library.templateDefault')"
            :hint="form.rename_files ? t('library.templateHint', { vars: templateVars }) : t('library.templateFolderHint', { vars: templateVars })" persistent-hint :error-messages="templateError || undefined" data-test="template" />
          <div v-for="example in examples" :key="example.source" class="example">
            <span class="st-muted">{{ example.source }}</span> → {{ example.target }}
          </div>
        </section>
        <section>
          <div class="section-title">{{ t("library.mediaServer") }}</div>
          <div class="grid">
            <VSelect :model-value="form.server_id" clearable :label="t('library.server')" :placeholder="t('library.noServer')"
              :items="servers.map((entry) => ({ title: entry.name, value: entry.id }))" @update:model-value="pickServer" />
            <VSelect v-if="form.server_id !== null" v-model="form.server_library_id" :label="t('library.serverLibrary')"
              :items="serverLibraries" :error-messages="serverError || undefined" />
          </div>
        </section>
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact" rounded="lg">{{ saveError }}</VAlert>
        <div class="actions">
          <VBtn variant="text" @click="cancel">{{ t("common.cancel") }}</VBtn>
          <VBtn color="primary" :disabled="!canSave" :loading="saving" data-test="save" @click="save">{{ t("common.save") }}</VBtn>
        </div>
      </div>
  </VCard>
</template>

<style scoped>
/* Opening the settings only makes the card taller; it keeps its place and width in the grid. */
.library-card { padding: 20px; display: flex; flex-direction: column; container-type: inline-size; }
.head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.title { min-width: 0; }
.paths { display: flex; flex-direction: column; gap: 2px; margin-top: 16px; font-size: 14px; flex: 1; }
.path { display: flex; align-items: center; gap: 6px; min-width: 0; }
.path span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arrow { margin-left: 1px; }
.foot { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 14px; padding-top: 12px;
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.foot-text { flex: 0 0 100%; min-width: 0; }
.form { display: flex; flex-direction: column; gap: 18px; margin-top: 18px; }
.section-title { font-size: 13px; font-weight: 600; opacity: 0.7; margin-bottom: 10px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px; row-gap: 16px; }
.switches { margin-top: 4px; }
.example { font-size: 12px; margin-top: 6px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
@container (max-width: 599px) {
  .grid { grid-template-columns: minmax(0, 1fr); }
}
</style>

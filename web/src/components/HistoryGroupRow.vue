<script setup lang="ts">
import { mdiArrowRight, mdiChevronDown, mdiChevronRight, mdiClose, mdiCloudSyncOutline, mdiFolderOpenOutline, mdiImageMultipleOutline, mdiPencilOutline, mdiRefresh, mdiRestore } from "@mdi/js";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { history as historyApi, items as itemApi, type HistoryGroup, type Item } from "@/api";
import type { ApiError } from "@/api/client";
import { relativeTime, shortTime } from "@/composables/format";
import { ask } from "@/composables/confirm";
import { bridge } from "@/composables/desktop";
import { notify } from "@/composables/notify";
import { useAuth } from "@/stores/auth";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";
import CoverWallDialog from "./CoverWallDialog.vue";
import MetadataDialog from "./MetadataDialog.vue";
import ReorganizeDialog from "./ReorganizeDialog.vue";
import StatusTag from "./StatusTag.vue";

const ROW = 52;
const VIRTUAL_FROM = 60; // a plain list below this; 867 chapters scroll virtually
const props = defineProps<{ group: HistoryGroup; open: boolean }>();
const emit = defineEmits<{ toggle: []; openItem: [id: number]; changed: [] }>();
const { t } = useI18n();
const jobs = useJobs();
const libraries = useLibraries();
const auth = useAuth();
const items = ref<Item[]>([]);
const loading = ref(false);
const busy = ref(false);
const picked = ref(new Set<number>());
const reorganizing = ref<Item[] | null>(null);
const editing = ref<Item[] | null>(null);
const coverWall = ref<Item[] | null>(null);
const broken = ref(false);

// Only a Bangumi cover can be found from the id alone; other sources show the placeholder.
const cover = computed(() => (props.group.subject_id && (props.group.subject_source ?? "bangumi") === "bangumi"
  ? `https://api.bgm.tv/v0/subjects/${props.group.subject_id}/image?type=small` : null));
// Where the first organized file of this group went.
const outputFolder = computed(() => {
  const target = items.value.find((item) => item.target_path)?.target_path;
  const root = libraries.list.find((library) => library.id === props.group.library_id)?.library_dir;
  if (!target || !root) return null;
  const parts = target.split(/[/\\]/).slice(0, -1);
  const separator = root.includes("\\") ? "\\" : "/";
  return [root.replace(/[/\\]$/, ""), ...parts].join(separator);
});
const title = computed(() => props.group.series || props.group.folder);
const kind = computed(() => libraries.kindOf(props.group.library_id));
const targets = computed(() => (picked.value.size ? items.value.filter((item) => picked.value.has(item.id)) : items.value));
// Unticked means the whole folder: the loaded rows (a deep-linked folder has no ids of its own yet).
const targetIds = computed(() => {
  if (picked.value.size) return [...picked.value];
  return items.value.length ? items.value.map((item) => item.id) : props.group.item_ids;
});
const publishedTargets = computed(() => targets.value.filter((item) => item.status === "published"));

async function load() {
  loading.value = true;
  try {
    items.value = await historyApi.items(props.group.library_id, props.group.group_key);
    picked.value = new Set([...picked.value].filter((id) => items.value.some((item) => item.id === id)));
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    loading.value = false;
  }
}

watch(() => [props.open, props.group.updated_at], () => props.open && load(), { immediate: true });

function toggle(id: number, on: boolean | null) {
  const next = new Set(picked.value);
  if (on) next.add(id);
  else next.delete(id);
  picked.value = next;
}

async function run(kind: "retry" | "cancel") {
  if (kind === "cancel" && !(await ask(t("history.cancelTitle"), t("history.cancelText", { count: targetIds.value.length }), true))) return;
  busy.value = true;
  try {
    if (kind === "retry") await jobs.submit(itemApi.retry(targetIds.value), t("jobs.kind.retry"));
    else {
      await itemApi.cancel(targetIds.value);
      libraries.refresh().catch(() => {});
    }
    picked.value = new Set();
    emit("changed");
    await load();
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}

async function refreshMetadata() {
  busy.value = true;
  try {
    const job = await jobs.submit(itemApi.refreshMetadata({ item_ids: publishedTargets.value.map((item) => item.id) }), t("jobs.kind.refresh_metadata"));
    const result = job.result as Record<string, number>;
    const counts = { refreshed: result.refreshed ?? 0, unchanged: result.unchanged ?? 0, skipped: result.skipped ?? 0, failed: result.failed ?? 0 };
    if (counts.failed) notify.warning(t("history.refreshedPartly", counts));
    else notify.success(t("history.refreshed", counts));
    picked.value = new Set();
    emit("changed");
    await load();
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}

async function reorganized(result: Record<string, number>) {
  reorganizing.value = null;
  if (result.skipped && !result.replanned) notify.warning(t("history.sourceGone"));
  else notify.success(t("history.reorganized"));
  picked.value = new Set();
  emit("changed");
  await load();
}

async function edited(result: Record<string, number>) {
  editing.value = null;
  if (result.failed) notify.warning(t("history.metadataPartly", { edited: result.edited ?? 0, failed: result.failed }));
  else notify.success(t("history.metadataEdited", { count: result.edited ?? 0 }));
  picked.value = new Set();
  emit("changed");
  await load();
}

function missing(item: Item) {
  return item.status === "published" && item.subject_id === null && !(item.overrides as Record<string, unknown>)?.metadata;
}

function fileName(item: Item) {
  return item.target_path?.split("/").pop() ?? "—";
}
</script>

<template>
  <VCard class="group" data-test="history-group">
    <div class="head" role="button" tabindex="0" :aria-expanded="open" @click="emit('toggle')" @keydown.enter="emit('toggle')">
      <VIcon :icon="open ? mdiChevronDown : mdiChevronRight" size="20" class="st-muted" />
      <div class="cover">
        <img v-if="cover && !broken" :src="cover" alt="" loading="lazy" referrerpolicy="no-referrer" @error="broken = true" />
        <span v-else>{{ title.slice(0, 1) }}</span>
      </div>
      <div class="info">
        <div class="name">
          <VChip size="x-small" variant="tonal" :color="kind === 'novel' ? 'info' : 'primary'" class="kind" label
            data-test="kind-tag">
{{ t(`library.${kind}`) }}
</VChip>
          <span>{{ title }}</span>
        </div>
        <div v-if="group.folder !== title" class="st-muted text-caption folder" data-test="group-folder">{{ group.folder }}</div>
      </div>
      <div class="counts">
        <StatusTag v-for="(count, status) in group.counts" :key="status" :status="String(status)" :count="count" />
        <StatusTag v-if="group.missing_metadata" status="missing_metadata" :count="group.missing_metadata" />
      </div>
      <div class="time st-muted text-caption" :title="shortTime(group.updated_at)">{{ relativeTime(group.updated_at) }}</div>
    </div>
    <div v-if="open" class="body">
      <div class="toolbar">
        <span class="st-muted text-caption">
          {{ picked.size ? t("history.selected", { count: picked.size }) : t("history.actOnAll") }}
        </span>
        <VSpacer />
        <VBtn v-if="auth.desktop" size="small" variant="tonal" color="primary" :prepend-icon="mdiFolderOpenOutline"
          :disabled="!outputFolder" data-test="group-open-folder" @click="outputFolder && bridge()?.openPath(outputFolder)">
          {{ t("desktop.openFolder") }}
        </VBtn>
        <VBtn size="small" variant="tonal" color="primary" :prepend-icon="mdiPencilOutline"
          :disabled="busy || !publishedTargets.length" data-test="group-metadata" @click="editing = publishedTargets">
{{ t("history.editMetadata") }}
</VBtn>
        <VBtn v-if="kind === 'manga'" size="small" variant="tonal" color="primary" :prepend-icon="mdiImageMultipleOutline" :disabled="busy || !publishedTargets.length"
          data-test="group-covers" @click="coverWall = publishedTargets">
{{ t("covers.open") }}
</VBtn>
        <VBtn size="small" variant="tonal" color="primary" :prepend-icon="mdiCloudSyncOutline" :disabled="busy || !publishedTargets.length"
          data-test="group-refresh" @click="refreshMetadata">
{{ t("history.refreshMetadata") }}
</VBtn>
        <VBtn size="small" variant="tonal" color="primary" :prepend-icon="mdiRestore" :disabled="busy || !publishedTargets.length"
          data-test="group-reorganize" @click="reorganizing = publishedTargets">
{{ t("history.reorganize") }}
</VBtn>
        <VBtn size="small" variant="tonal" :prepend-icon="mdiRefresh" :disabled="busy" :loading="busy" data-test="group-retry"
          @click="run('retry')">
{{ t("common.retry") }}
</VBtn>
        <VBtn size="small" variant="text" :prepend-icon="mdiClose" :disabled="busy" data-test="group-cancel"
          @click="run('cancel')">
{{ t("common.cancel") }}
</VBtn>
      </div>
      <VProgressLinear v-if="loading" indeterminate color="primary" />
      <div v-if="items.length < VIRTUAL_FROM" data-test="group-items">
        <div v-for="item in items" :key="item.id" class="row" data-test="group-item">
          <VCheckboxBtn :model-value="picked.has(item.id)" density="compact" :aria-label="item.source_name"
            @update:model-value="(on: boolean | null) => toggle(item.id, on)" />
          <StatusTag :status="item.status" :reason="item.review_reason" />
          <StatusTag v-if="missing(item)" status="missing_metadata" />
          <span class="source">{{ item.source_name }}</span>
          <VIcon :icon="mdiArrowRight" size="14" class="st-muted arrow" />
          <span class="target">{{ fileName(item) }}</span>
          <VSpacer />
          <VBtn size="small" variant="text" data-test="item-details" @click="emit('openItem', item.id)">{{ t("history.details") }}</VBtn>
        </div>
      </div>
      <VVirtualScroll v-else :items="items" :item-height="ROW" :height="10 * ROW" item-key="id" data-test="group-items">
        <template #default="{ item }">
          <div class="row" data-test="group-item">
            <VCheckboxBtn :model-value="picked.has(item.id)" density="compact" :aria-label="item.source_name"
              @update:model-value="(on: boolean | null) => toggle(item.id, on)" />
            <StatusTag :status="item.status" :reason="item.review_reason" />
            <StatusTag v-if="missing(item)" status="missing_metadata" />
            <span class="source">{{ item.source_name }}</span>
            <VIcon :icon="mdiArrowRight" size="14" class="st-muted arrow" />
            <span class="target">{{ fileName(item) }}</span>
            <VSpacer />
            <VBtn size="small" variant="text" data-test="item-details" @click="emit('openItem', item.id)">{{ t("history.details") }}</VBtn>
          </div>
        </template>
      </VVirtualScroll>
    </div>
    <CoverWallDialog v-if="coverWall" :items="coverWall" :title="title" @close="coverWall = null" />
    <MetadataDialog v-if="editing" :items="editing" :kind="kind" :title="title" @close="editing = null" @done="edited" />
    <ReorganizeDialog v-if="reorganizing" :items="reorganizing" @close="reorganizing = null" @done="reorganized" />
  </VCard>
</template>

<style scoped>
.group { padding: 0; overflow: hidden; }
.head { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; }
.head:hover { background: rgba(var(--v-theme-primary), 0.03); }
.head:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; }
.cover {
  width: 40px; height: 54px; border-radius: 6px; overflow: hidden; flex: none; display: grid; place-items: center;
  background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary)); font-weight: 700;
}
.cover img { width: 100%; height: 100%; object-fit: cover; }
.info { flex: 1; min-width: 0; }
.name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kind { margin-right: 6px; vertical-align: 1px; }
.folder { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.counts { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.time { width: 72px; text-align: right; flex: none; }
.body { border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); padding: 8px 16px 12px; }
.toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 0 8px; }
.row { display: flex; align-items: center; gap: 10px; height: 52px; font-size: 13px; }
.source { opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 0 1 auto; }
.target { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
@media (max-width: 699px) {
  .head { flex-wrap: wrap; }
  .counts { width: 100%; justify-content: flex-start; padding-left: 32px; }
  .time { display: none; }
  .source, .arrow { display: none; }
}
</style>

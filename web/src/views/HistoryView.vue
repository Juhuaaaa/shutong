<script setup lang="ts">
import { mdiChevronLeft, mdiChevronRight, mdiMagnify } from "@mdi/js";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { history as historyApi, type HistoryGroup } from "@/api";
import type { ApiError } from "@/api/client";
import HistoryGroupRow from "@/components/HistoryGroupRow.vue";
import ItemDrawer from "@/components/ItemDrawer.vue";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";

const PAGE = 30;
// Only states worth looking for; the in-between ones (parsed, planned, ready, building) pass in minutes.
const STATUSES = ["published", "needs_review", "failed", "duplicate", "cancelled"];

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const jobs = useJobs();
const groups = ref<HistoryGroup[]>([]);
const total = ref(0);
const loading = ref(false);

const status = computed(() => (typeof route.query.status === "string" ? route.query.status : ""));
const query = ref(typeof route.query.q === "string" ? route.query.q : "");
const page = computed(() => Math.max(1, Number(route.query.page ?? 1) || 1));
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE)));
const openGroup = computed(() => (typeof route.query.group === "string" ? route.query.group : null));
const openItem = computed(() => (route.query.item ? Number(route.query.item) : null));

const statusOptions = computed(() => [{ title: t("history.allStatuses"), value: "" },
  ...STATUSES.map((value) => ({ title: t(`status.${value}`), value })),
  { title: t("status.missing_metadata"), value: "missing_metadata" }]);

function setQuery(changes: Record<string, string | undefined>) {
  const next: Record<string, string> = {};
  for (const [key, value] of Object.entries({ ...route.query, ...changes })) {
    if (typeof value === "string" && value) next[key] = value;
  }
  router.replace({ query: next });
}

async function load() {
  loading.value = true;
  try {
    const missing = status.value === "missing_metadata";
    const result = await historyApi.groups({ status: missing ? undefined : status.value || undefined,
      missing_metadata: missing || undefined,
      q: query.value || undefined, limit: PAGE, offset: (page.value - 1) * PAGE });
    groups.value = result.groups;
    total.value = result.total;
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(query, (value) => {
  clearTimeout(timer);
  timer = setTimeout(() => setQuery({ q: value, page: undefined }), 300);
});
watch(() => [status.value, route.query.q, page.value], load);
onMounted(load);
const stop = jobs.onFinished(["scan", "execute", "confirm", "reorganize", "retry", "reidentify", "metadata"], () => load());
onUnmounted(stop);

// Folders of different libraries can share a name, so a folder is "<library id>:<folder>".
function keyOf(group: HistoryGroup) {
  return `${group.library_id}:${group.group_key}`;
}

const shown = computed(() => {
  // A folder opened from elsewhere (dashboard) stays visible even when it is not on this page.
  const open = openGroup.value;
  if (!open || groups.value.some((group) => keyOf(group) === open) || loading.value) return groups.value;
  const split = open.indexOf(":");
  const libraryId = Number(open.slice(0, split));
  if (split < 1 || !Number.isInteger(libraryId)) return groups.value;
  const folder = open.slice(split + 1);
  return [{ library_id: libraryId, group_key: folder, folder, series: null, subject_id: null,
    counts: {}, total: 0, updated_at: "", item_ids: [], missing_metadata: 0 } as HistoryGroup, ...groups.value];
});
</script>

<template>
  <div class="st-page">
    <div class="toolbar">
      <h1 class="st-page-title">{{ t("nav.history") }}</h1>
      <VSpacer />
      <VSelect :model-value="status" :items="statusOptions" density="compact" hide-details class="status"
        @update:model-value="(value: string) => setQuery({ status: value, page: undefined })" />
      <VTextField v-model="query" density="compact" hide-details clearable :prepend-inner-icon="mdiMagnify"
        :placeholder="t('history.search')" class="search" />
    </div>
    <VProgressLinear v-if="loading" indeterminate color="primary" rounded />
    <VCard v-if="!loading && !shown.length" class="pa-8 text-center st-muted">{{ t("history.empty") }}</VCard>
    <div class="groups">
      <HistoryGroupRow v-for="group in shown" :key="keyOf(group)" :group="group" :open="keyOf(group) === openGroup"
        @toggle="setQuery({ group: keyOf(group) === openGroup ? undefined : keyOf(group) })"
        @open-item="(id: number) => setQuery({ item: String(id) })" @changed="load" />
    </div>
    <div class="pager">
      <span class="st-muted text-body-2">{{ t("history.folders", { count: total }) }}</span>
      <VSpacer />
      <VBtn icon variant="text" size="small" :disabled="page <= 1" :aria-label="t('history.prev')"
        @click="setQuery({ page: String(page - 1) })">
<VIcon :icon="mdiChevronLeft" />
</VBtn>
      <span class="text-body-2">{{ t("history.page", { page, pages }) }}</span>
      <VBtn icon variant="text" size="small" data-test="next-page" :disabled="page >= pages" :aria-label="t('history.next')"
        @click="setQuery({ page: String(page + 1) })">
<VIcon :icon="mdiChevronRight" />
</VBtn>
    </div>
    <ItemDrawer :item-id="openItem" @close="setQuery({ item: undefined })" @changed="load" />
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.status { max-width: 160px; }
.search { max-width: 280px; min-width: 200px; }
.groups { display: flex; flex-direction: column; gap: 10px; }
.pager { display: flex; align-items: center; gap: 8px; }
@media (max-width: 599px) {
  .status, .search { max-width: none; flex: 1 1 140px; }
}
</style>

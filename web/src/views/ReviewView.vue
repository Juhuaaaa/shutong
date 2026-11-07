<script setup lang="ts">
import { mdiRefresh } from "@mdi/js";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as libraryApi, review, settings, type Choices, type ReviewGroup } from "@/api";
import type { ApiError } from "@/api/client";
import ReviewDetail from "@/components/ReviewDetail.vue";
import ReviewGroupList from "@/components/ReviewGroupList.vue";
import { ask } from "@/composables/confirm";
import { notify } from "@/composables/notify";
import { editionOf } from "@/composables/volume";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

const { t } = useI18n();
const jobs = useJobs();
const libraries = useLibraries();
const groups = ref<ReviewGroup[]>([]);
const selectedKey = ref<string | null>(null);
const seriesByLibrary = ref<Record<number, string[]>>({});
const aiReady = ref(false);
const loading = ref(false);
const busy = ref(false);
const list = ref<InstanceType<typeof ReviewGroupList> | null>(null);

const selected = computed(() => groups.value.find((group) => group.key === selectedKey.value) ?? null);
const kind = computed(() => libraries.kindOf(selected.value?.library_id ?? 0));
const editions = computed(() => {
  const series = selected.value ? (seriesByLibrary.value[selected.value.library_id] ?? []) : [];
  return [...new Set(series.map(editionOf).filter((edition): edition is string => edition !== null))].sort();
});

// Editions already in the selected group's library, fetched once per library.
watch(() => selected.value?.library_id, async (id) => {
  if (id === undefined || id in seriesByLibrary.value) return;
  const series = await libraryApi.series(id).catch(() => [] as string[]);
  seriesByLibrary.value = { ...seriesByLibrary.value, [id]: series };
});

async function load() {
  loading.value = true;
  try {
    const [found, config] = await Promise.all([
      review.groups(),
      settings.get().catch(() => ({}) as Record<string, unknown>),
    ]);
    groups.value = found;
    aiReady.value = Boolean(config["ai.base_url"] && config["ai.model"]) && config["ai.api_key"] === "已设置";
    if (!found.some((group) => group.key === selectedKey.value)) selectedKey.value = found[0]?.key ?? null;
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    loading.value = false;
  }
}

onMounted(load);
const stop = jobs.onFinished(["scan", "retry", "reorganize"], () => load());
onUnmounted(stop);

function next(fromKey: string) {
  const visible = list.value?.shown ?? groups.value;
  const index = visible.findIndex((group) => group.key === fromKey);
  const following = visible[index + 1] ?? visible[index - 1] ?? null;
  return following && following.key !== fromKey ? following.key : null;
}

async function confirm(choices: Choices, ids: number[]) {
  const group = selected.value;
  if (!group) return;
  busy.value = true;
  try {
    await jobs.submit(review.confirm(ids, choices), t("jobs.kind.confirm"));
    if (ids.length < group.item_ids.length) {
      // Part of the folder: the rest stays here to be sorted next, and what could not be settled comes back.
      await load();
    } else {
      const following = next(group.key);
      groups.value = groups.value.filter((entry) => entry.key !== group.key);
      selectedKey.value = following;
    }
    notify.success(t("review.confirmed"));
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}

async function reidentify(target: { item_ids: number[] }) {
  busy.value = true;
  try {
    const job = await jobs.submit(review.reidentify(target), t("jobs.kind.reidentify"));
    const result = job.result as Record<string, number>;
    notify.success(t("review.reidentified", { executed: result.executed ?? 0, review: result.needs_review ?? 0 }));
    await Promise.all([load(), libraries.refresh().catch(() => {})]);
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}

async function reidentifyAll() {
  const count = groups.value.reduce((sum, group) => sum + group.count, 0);
  if (await ask(t("review.reidentifyAllTitle", { count }), t("review.reidentifyAllText"))) {
    await reidentify({ item_ids: groups.value.flatMap((group) => group.item_ids) });
  }
}

function skip() {
  if (selectedKey.value) selectedKey.value = next(selectedKey.value) ?? selectedKey.value;
}
</script>

<template>
  <div class="st-page review">
    <div class="toolbar">
      <h1 class="st-page-title">{{ t("nav.review") }}</h1>
      <VSpacer />
      <VBtn variant="tonal" color="primary" :prepend-icon="mdiRefresh" :disabled="busy || !groups.length" :loading="busy"
        data-test="reidentify-all" @click="reidentifyAll">
{{ t("review.reidentifyAll") }}
</VBtn>
    </div>
    <VProgressLinear v-if="loading" indeterminate color="primary" rounded />
    <VCard v-if="!loading && !groups.length" class="pa-8 text-center st-muted">{{ t("review.empty") }}</VCard>
    <div v-else class="split">
      <aside class="side">
        <ReviewGroupList ref="list" :groups="groups" :selected-key="selectedKey" @select="selectedKey = $event.key" />
      </aside>
      <section class="main">
        <ReviewDetail v-if="selected" :group="selected" :kind="kind" :editions="editions" :ai-ready="aiReady" :busy="busy"
          @confirm="confirm" @skip="skip" @reidentify="reidentify({ item_ids: selected.item_ids })" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; align-items: center; gap: 12px; }
.split { display: grid; grid-template-columns: minmax(240px, 340px) minmax(0, 1fr); gap: var(--st-gap); height: calc(100vh - 170px); }
.side { min-height: 0; display: flex; flex-direction: column; }
.main { overflow: auto; min-height: 0; padding-bottom: 4px; }
@media (max-width: 899px) {
  .split { grid-template-columns: minmax(0, 1fr); height: auto; }
  .side { height: 42vh; }
}
</style>

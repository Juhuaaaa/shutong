<script setup lang="ts">
import { mdiPlus } from "@mdi/js";
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as api, servers as serverApi, type Library, type Run, type Server } from "@/api";
import { ApiError } from "@/api/client";
import LibraryCard from "@/components/LibraryCard.vue";
import { scanSummary } from "@/composables/format";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

const { t } = useI18n();
const libraries = useLibraries();
const jobs = useJobs();
const runs = ref<Record<number, Run | null>>({});
const servers = ref<Server[]>([]);
const scanning = ref<Set<number>>(new Set());
const creating = ref(false);

function failed(error: unknown) {
  notify.error(error instanceof ApiError ? error.detail : String(error));
}

async function load() {
  await libraries.refresh();
  servers.value = await serverApi.list().catch(() => []);
  const entries = await Promise.all(libraries.list.map(async (library) => [library.id, (await api.runs(library.id))[0] ?? null]));
  runs.value = Object.fromEntries(entries);
}

onMounted(() => load().catch(failed));

async function scan(library: Library) {
  scanning.value = new Set([...scanning.value, library.id]);
  try {
    const job = await jobs.submit(api.scan(library.id), t("jobs.scanOf", { name: library.name }));
    notify.success(scanSummary((job.result as { counts?: Record<string, number> }).counts ?? {}));
    await load();
  } catch (error) {
    failed(error);
  } finally {
    scanning.value = new Set([...scanning.value].filter((id) => id !== library.id));
  }
}

async function saved() {
  creating.value = false;
  await load().catch(failed);
}
</script>

<template>
  <div class="st-page">
    <div class="d-flex align-center">
      <h1 class="st-page-title">{{ t("nav.libraries") }}</h1>
      <VSpacer />
      <VBtn color="primary" :prepend-icon="mdiPlus" :disabled="creating" data-test="create" @click="creating = true">
        {{ t("library.create") }}
      </VBtn>
    </div>
    <VCard v-if="libraries.loaded && !libraries.list.length && !creating" class="pa-8 text-center st-muted">
      {{ t("library.empty") }}
    </VCard>
    <div class="cards">
      <LibraryCard v-if="creating" :library="null" @saved="saved" @cancel="creating = false" />
      <LibraryCard v-for="library in libraries.list" :key="library.id"
        :library="library" :counts="libraries.summaries[library.id] ?? {}" :last-run="runs[library.id] ?? null"
        :servers="servers" :scanning="scanning.has(library.id)" @scan="scan(library)" @saved="saved" />
    </div>
  </div>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 400px), 1fr)); gap: 16px; align-items: start; }
</style>

<script setup lang="ts">
import { mdiPlus, mdiTrayArrowDown } from "@mdi/js";
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { dashboard as api, libraries as librariesApi, type Dashboard } from "@/api";
import { ApiError } from "@/api/client";
import QuickActions from "@/components/dashboard/QuickActions.vue";
import RecentCard from "@/components/dashboard/RecentCard.vue";
import StatCard from "@/components/dashboard/StatCard.vue";
import StorageCard from "@/components/dashboard/StorageCard.vue";
import { scanSummary } from "@/composables/format";
import { useAuth } from "@/stores/auth";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";

const { t } = useI18n();
const jobs = useJobs();
const data = ref<Dashboard | null>(null);
const error = ref("");
const auth = useAuth();
const scanning = ref(new Set<number>());

async function load() {
  try {
    data.value = await api.get();
    error.value = "";
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.detail : String(reason);
  }
}

onMounted(load);
const stop = jobs.onFinished(["scan", "execute", "confirm", "reorganize", "retry", "reidentify", "metadata"], () => load());
onUnmounted(stop);

async function scan(library: Dashboard["libraries"][number]) {
  scanning.value = new Set([...scanning.value, library.id]);
  try {
    const job = await jobs.submit(librariesApi.scan(library.id), t("jobs.scanOf", { name: library.name }));
    notify.success(scanSummary((job.result as { counts?: Record<string, number> }).counts ?? {}));
  } catch (reason) {
    notify.error(reason instanceof ApiError ? reason.detail : String(reason));
  } finally {
    scanning.value = new Set([...scanning.value].filter((id) => id !== library.id));
  }
}
</script>

<template>
  <div class="st-page">
    <VAlert v-if="error" type="error" variant="tonal" rounded="lg">{{ error }}</VAlert>
    <template v-if="data">
      <VCard v-if="!data.libraries.length" class="pa-8 text-center">
        <p class="st-muted mb-4">{{ t("dashboard.noLibraries") }}</p>
        <VBtn color="primary" :prepend-icon="mdiPlus" :to="{ name: 'libraries' }">{{ t("dashboard.createLibrary") }}</VBtn>
      </VCard>
      <VCard v-if="auth.desktop" class="drop-hint pa-6 mb-4" data-test="drop-hint">
        <VIcon :icon="mdiTrayArrowDown" size="32" color="primary" />
        <div>
          <div class="font-weight-medium">{{ t("desktop.dropHint.title") }}</div>
          <div class="st-muted text-caption">{{ t("desktop.dropHint.text") }}</div>
        </div>
      </VCard>
      <div class="libraries">
        <StatCard v-for="library in data.libraries" :key="library.id" :library="library" />
      </div>
      <div class="columns">
        <RecentCard :recent="data.recent" />
        <div class="side">
          <QuickActions :libraries="data.libraries" :scanning="scanning" @scan="scan" />
          <StorageCard v-if="data.storage.length" :storage="data.storage" />
        </div>
      </div>
    </template>
    <VSkeletonLoader v-else-if="!error" type="card, card" />
  </div>
</template>

<style scoped>
.drop-hint { display: flex; align-items: center; gap: 16px; }
.libraries { display: grid; gap: var(--st-gap); grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }
.columns { display: grid; gap: var(--st-gap); grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); align-items: start; }
.side { display: flex; flex-direction: column; gap: var(--st-gap); }
@media (max-width: 1100px) {
  .columns { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 599px) {
  .libraries { grid-template-columns: minmax(0, 1fr); }
}
</style>

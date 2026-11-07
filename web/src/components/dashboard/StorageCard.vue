<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { Dashboard } from "@/api";
import { humanSize } from "@/composables/format";

defineProps<{ storage: Dashboard["storage"] }>();
const { t } = useI18n();
const percent = (entry: Dashboard["storage"][number]) => (entry.total ? Math.round((entry.used / entry.total) * 100) : 0);
</script>

<template>
  <VCard class="pa-5" data-test="storage">
    <div class="text-subtitle-1 font-weight-bold mb-3">{{ t("dashboard.storage") }}</div>
    <div v-for="entry in storage" :key="entry.path" class="mb-4">
      <div class="d-flex text-body-2 mb-1">
        <span class="path">{{ entry.path }}</span>
        <VSpacer />
        <strong>{{ percent(entry) }}%</strong>
      </div>
      <VProgressLinear :model-value="percent(entry)" :color="percent(entry) > 90 ? 'error' : 'primary'" height="8" rounded />
      <div class="st-muted text-caption mt-1">
        {{ t("dashboard.storageUsed", { used: humanSize(entry.used), total: humanSize(entry.total) }) }}
      </div>
    </div>
  </VCard>
</template>

<style scoped>
.path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
</style>

<script setup lang="ts">
import { mdiAlertCircleOutline, mdiBookOpenPageVariantOutline, mdiBookshelf, mdiCheckDecagramOutline,
  mdiTrendingUp } from "@mdi/js";
import { useI18n } from "vue-i18n";
import type { Dashboard } from "@/api";

defineProps<{ library: Dashboard["libraries"][number] }>();
const { t } = useI18n();
type Key = "series" | "volumes" | "month_new" | "needs_review";
const stats: { key: Key; icon: string; color: string; to?: string }[] = [
  { key: "series", icon: mdiBookshelf, color: "primary" },
  { key: "volumes", icon: mdiBookOpenPageVariantOutline, color: "info" },
  { key: "month_new", icon: mdiTrendingUp, color: "success" },
  { key: "needs_review", icon: mdiCheckDecagramOutline, color: "warning", to: "review" },
];
</script>

<template>
  <VCard class="pa-5" data-test="library-stats">
    <div class="d-flex align-center mb-4 ga-2">
      <span class="text-subtitle-1 font-weight-bold">{{ library.name }}</span>
      <VChip size="small" variant="tonal">{{ t(`library.${library.kind}`) }}</VChip>
      <VSpacer />
      <VChip v-if="!library.available" size="small" color="error" variant="tonal">{{ t("library.unavailable") }}</VChip>
      <VChip v-else-if="library.failed" size="small" color="error" variant="tonal" :prepend-icon="mdiAlertCircleOutline">
        {{ t("dashboard.failed", { count: library.failed }) }}
      </VChip>
    </div>
    <div class="stats">
      <component :is="stat.to && library[stat.key] ? 'RouterLink' : 'div'" v-for="stat in stats" :key="stat.key"
        :to="stat.to ? { name: stat.to } : undefined" class="stat" :data-test="`stat-${stat.key}`">
        <VAvatar :color="stat.color" variant="tonal" size="40" rounded="lg"><VIcon :icon="stat.icon" size="22" /></VAvatar>
        <div>
          <div class="value">{{ library[stat.key].toLocaleString() }}</div>
          <div class="label">{{ t(`dashboard.stats.${stat.key}`) }}</div>
        </div>
      </component>
    </div>
  </VCard>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 16px; }
.stat { display: flex; align-items: center; gap: 12px; color: inherit; text-decoration: none; border-radius: 12px; }
a.stat:hover .value { color: rgb(var(--v-theme-primary)); }
.value { font-size: 20px; font-weight: 700; line-height: 1.2; }
.label { font-size: 12px; opacity: 0.6; }
</style>

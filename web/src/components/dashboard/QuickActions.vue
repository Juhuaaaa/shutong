<script setup lang="ts">
import { mdiCheckDecagramOutline, mdiCogOutline, mdiRefresh } from "@mdi/js";
import { useI18n } from "vue-i18n";
import type { Dashboard } from "@/api";
import { useAuth } from "@/stores/auth";

defineProps<{ libraries: Dashboard["libraries"]; scanning: Set<number> }>();
defineEmits<{ scan: [library: Dashboard["libraries"][number]] }>();
const { t } = useI18n();
const auth = useAuth();
</script>

<template>
  <VCard class="pa-5">
    <div class="text-subtitle-1 font-weight-bold mb-3">{{ t("dashboard.actions") }}</div>
    <div class="actions">
      <VBtn v-for="library in auth.desktop ? [] : libraries" :key="library.id" variant="tonal" color="primary" :prepend-icon="mdiRefresh"
        :loading="scanning.has(library.id)" :disabled="!library.available" :data-test="`scan-${library.id}`"
        @click="$emit('scan', library)">
        {{ t("dashboard.scan", { name: library.name }) }}
      </VBtn>
      <VBtn v-if="libraries.length" variant="tonal" color="warning" :prepend-icon="mdiCheckDecagramOutline"
        :to="{ name: 'review' }">
{{ t("dashboard.goReview") }}
</VBtn>
      <VBtn variant="tonal" color="secondary" :prepend-icon="mdiCogOutline" :to="{ name: 'settings' }">{{ t("dashboard.settings") }}</VBtn>
    </div>
  </VCard>
</template>

<style scoped>
.actions { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.actions :deep(.v-btn) { justify-content: flex-start; }
</style>

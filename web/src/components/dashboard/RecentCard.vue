<script setup lang="ts">
import { mdiCheckCircle } from "@mdi/js";
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import type { Dashboard } from "@/api";
import { relativeTime } from "@/composables/format";

defineProps<{ recent: Dashboard["recent"] }>();
const { t } = useI18n();
const router = useRouter();
const broken = ref(new Set<string>());

function open(group: Dashboard["recent"][number]) {
  router.push({ name: "history", query: { group: key(group) } });
}

function key(group: Dashboard["recent"][number]) {
  return `${group.library_id}:${group.group_key}`;
}
</script>

<template>
  <VCard class="pa-5">
    <div class="text-subtitle-1 font-weight-bold mb-3">{{ t("dashboard.recent") }}</div>
    <div v-if="!recent.length" class="st-muted py-6 text-center">{{ t("dashboard.recentEmpty") }}</div>
    <div v-for="group in recent" :key="key(group)" class="row" role="link" tabindex="0" data-test="recent"
      @click="open(group)" @keydown.enter="open(group)">
      <div class="cover">
        <img v-if="group.image && !broken.has(key(group))" :src="group.image" alt="" loading="lazy"
          referrerpolicy="no-referrer" @error="broken = new Set([...broken, key(group)])" />
        <span v-else>{{ (group.series || group.group_key).slice(0, 1) }}</span>
      </div>
      <div class="info">
        <div class="name">{{ group.series || group.group_key }}</div>
        <div class="st-muted text-caption folder">{{ group.group_key }}</div>
      </div>
      <div class="meta">
        <div class="text-body-2">{{ t("dashboard.published", { count: group.published }) }}</div>
        <div class="st-muted text-caption">{{ relativeTime(group.at) }}</div>
      </div>
      <VIcon :icon="mdiCheckCircle" color="success" size="20" />
    </div>
  </VCard>
</template>

<style scoped>
.row {
  display: flex; align-items: center; gap: 14px; padding: 10px 8px; border-radius: 12px; cursor: pointer;
}
.row:hover, .row:focus-visible { background: rgba(var(--v-theme-primary), 0.06); outline: none; }
.cover {
  width: 44px; height: 60px; border-radius: 8px; overflow: hidden; flex: none; display: grid; place-items: center;
  background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary)); font-weight: 700; font-size: 18px;
}
.cover img { width: 100%; height: 100%; object-fit: cover; }
.info { flex: 1; min-width: 0; }
.name, .folder { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.name { font-weight: 600; }
.meta { text-align: right; flex: none; }
</style>

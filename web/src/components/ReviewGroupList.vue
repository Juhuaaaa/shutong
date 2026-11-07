<script setup lang="ts">
import { mdiMagnify } from "@mdi/js";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import type { ReviewGroup } from "@/api";
import { useLibraries } from "@/stores/libraries";

const props = defineProps<{ groups: ReviewGroup[]; selectedKey: string | null }>();
const emit = defineEmits<{ select: [group: ReviewGroup] }>();
const { t } = useI18n();
const libraries = useLibraries();
const VIRTUAL_FROM = 60; // a plain list below this; thousands of groups scroll virtually
const reason = ref("");
const query = ref("");

const reasons = computed(() => [
  { title: t("review.allReasons"), value: "" },
  ...["naming", "volume", "metadata", "conflict"].map((value) => ({ title: t(`reason.${value}`), value })),
]);
const shown = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return props.groups.filter((group) => (!reason.value || group.reasons.includes(reason.value))
    && (!needle || group.folder.toLowerCase().includes(needle) || group.title_hint.toLowerCase().includes(needle)));
});
defineExpose({ shown });
</script>

<template>
  <VCard class="list">
    <div class="filters">
      <VSelect v-model="reason" :items="reasons" density="compact" hide-details />
      <VTextField v-model="query" density="compact" hide-details clearable :prepend-inner-icon="mdiMagnify"
        :placeholder="t('review.filter')" />
      <div class="st-muted text-caption">{{ t("review.groups", { count: shown.length }) }}</div>
    </div>
    <div v-if="shown.length < VIRTUAL_FROM" class="rows plain" role="listbox">
      <div v-for="item in shown" :key="item.key" data-test="group-row" class="row" :class="{ active: item.key === selectedKey }"
        role="option" :aria-selected="item.key === selectedKey" tabindex="0" @click="emit('select', item)"
        @keydown.enter="emit('select', item)">
        <span class="name"><span class="kind" data-test="kind-tag">{{ t(`library.${libraries.kindOf(item.library_id)}`) }}</span>{{ item.folder }}</span>
        <span class="meta">
          {{ item.count }} {{ t("review.volumesShort") }}
          <span v-for="entry in item.reasons" :key="entry" class="reason">{{ t(`reason.${entry}`) }}</span>
        </span>
      </div>
    </div>
    <VVirtualScroll v-else :items="shown" :item-height="60" item-key="key" class="rows" role="listbox">
      <template #default="{ item }">
        <div data-test="group-row" class="row" :class="{ active: item.key === selectedKey }" role="option"
          :aria-selected="item.key === selectedKey" tabindex="0" @click="emit('select', item)" @keydown.enter="emit('select', item)">
          <span class="name"><span class="kind" data-test="kind-tag">{{ t(`library.${libraries.kindOf(item.library_id)}`) }}</span>{{ item.folder }}</span>
          <span class="meta">
            {{ item.count }} {{ t("review.volumesShort") }}
            <span v-for="entry in item.reasons" :key="entry" class="reason">{{ t(`reason.${entry}`) }}</span>
          </span>
        </div>
      </template>
    </VVirtualScroll>
  </VCard>
</template>

<style scoped>
.list { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: 12px 8px 8px; }
.filters { display: flex; flex-direction: column; gap: 8px; padding: 0 6px 8px; }
.rows { flex: 1; min-height: 200px; }
.plain { overflow-y: auto; }
.row {
  height: 56px; margin: 2px 0; padding: 6px 12px; cursor: pointer; border-radius: 10px;
  display: flex; flex-direction: column; justify-content: center;
}
.row:hover { background: rgba(var(--v-theme-on-surface), 0.04); }
.row:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; }
.row.active { background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary)); }
.name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 500; }
.meta { font-size: 12px; opacity: 0.7; display: flex; gap: 6px; align-items: center; }
.kind { margin-right: 6px; padding: 0 5px; border-radius: 5px; font-size: 11px; font-weight: 600; background: rgba(var(--v-theme-primary), 0.12); color: rgb(var(--v-theme-primary)); }
.reason { padding: 0 6px; border-radius: 6px; background: rgba(var(--v-theme-warning), 0.15); color: rgb(var(--v-theme-warning)); }
</style>

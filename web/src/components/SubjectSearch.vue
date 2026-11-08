<script setup lang="ts">
import { mdiMagnify } from "@mdi/js";
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { metadata, type MetadataSource, type Subject } from "@/api";
import type { ApiError } from "@/api/client";
import { subjectRefOf } from "@/composables/volume";

const props = defineProps<{ kind: "manga" | "novel"; initial: string }>();
const emit = defineEmits<{ results: [subjects: Subject[]]; error: [message: string] }>();
/** The source searched; a typed number is an id in this source. */
const source = defineModel<string>("source", { default: "bangumi" });
const { t } = useI18n();
const query = ref(props.initial);
const busy = ref(false);
const sources = ref<MetadataSource[]>([]);
const enabled = computed(() => sources.value.filter((entry) => entry.enabled));
defineExpose({ search });

watch(() => props.initial, (value) => { query.value = value; });

onMounted(async () => {
  try {
    sources.value = await metadata.sources();
    if (enabled.value.length) source.value = enabled.value[0].name; // the first source asked is searched first
  } catch {
    sources.value = [];
  }
});

async function search() {
  if (!query.value.trim()) return;
  busy.value = true;
  try {
    const text = query.value.trim();
    const ref = /[/]/.test(text) || /^\d+$/.test(text) ? subjectRefOf(text, source.value) : null;
    emit("results", ref !== null ? [await metadata.subject(ref)] : await metadata.search(text, props.kind, source.value));
  } catch (error) {
    emit("error", (error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="subject-search">
    <VSelect v-if="enabled.length > 1" v-model="source" :items="enabled" item-title="label" item-value="name" density="compact"
      hide-details class="source" data-test="source-select" :aria-label="t('review.source')" />
    <VTextField v-model="query" density="compact" hide-details data-test="subject-search" :placeholder="t('review.searchSubject')"
      :prepend-inner-icon="mdiMagnify" @keyup.enter="search">
      <template #append-inner>
        <VBtn size="small" variant="tonal" color="primary" :loading="busy" @click="search">{{ t("review.search") }}</VBtn>
      </template>
    </VTextField>
  </div>
</template>

<style scoped>
.subject-search { display: flex; gap: 8px; align-items: center; }
.source { flex: 0 0 132px; }
</style>

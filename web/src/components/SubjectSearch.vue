<script setup lang="ts">
import { mdiMagnify } from "@mdi/js";
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { metadata, type Subject } from "@/api";
import type { ApiError } from "@/api/client";
import { subjectIdOf } from "@/composables/volume";

const props = defineProps<{ kind: "manga" | "novel"; initial: string }>();
const emit = defineEmits<{ results: [subjects: Subject[]]; error: [message: string] }>();
const { t } = useI18n();
const query = ref(props.initial);
const busy = ref(false);
defineExpose({ search });

watch(() => props.initial, (value) => { query.value = value; });

async function search() {
  if (!query.value.trim()) return;
  busy.value = true;
  try {
    const id = /[/]/.test(query.value) || /^\d+$/.test(query.value.trim()) ? subjectIdOf(query.value) : null;
    emit("results", id !== null ? [await metadata.subject(id)] : await metadata.search(query.value.trim(), props.kind));
  } catch (error) {
    emit("error", (error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <VTextField v-model="query" density="compact" hide-details data-test="bangumi-search" :placeholder="t('review.searchBangumi')" :prepend-inner-icon="mdiMagnify"
    @keyup.enter="search">
    <template #append-inner>
      <VBtn size="small" variant="tonal" color="primary" :loading="busy" @click="search">{{ t("review.search") }}</VBtn>
    </template>
  </VTextField>
</template>

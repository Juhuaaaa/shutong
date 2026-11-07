<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { items as itemApi, type Choices, type Item } from "@/api";
import type { ApiError } from "@/api/client";
import { isVolumeText } from "@/composables/volume";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

const props = defineProps<{ items: Item[] }>();
const emit = defineEmits<{ close: []; done: [result: Record<string, number>] }>();
const { t } = useI18n();
const jobs = useJobs();
const libraries = useLibraries();
const form = reactive({ title: "", edition: "", bgm: "", volume: "" });
const busy = ref(false);
const error = ref("");
const single = computed(() => props.items.length === 1);
const first = computed(() => props.items[0]);
const kind = computed(() => libraries.kindOf(first.value.library_id));
const badVolume = computed(() => Boolean(form.volume.trim()) && !isVolumeText(form.volume, kind.value));
const badBgm = computed(() => Boolean(form.bgm.trim()) && !/^[1-9]\d*$/.test(form.bgm.trim()));

async function submit() {
  const choices: Choices = {};
  if (form.title.trim()) choices.title = form.title.trim();
  if (form.edition.trim()) choices.edition = form.edition.trim();
  if (form.bgm.trim()) choices.bgm = Number(form.bgm.trim());
  if (single.value && form.volume.trim()) choices.volumes = { [String(first.value.id)]: form.volume.trim() };
  busy.value = true;
  error.value = "";
  try {
    const job = await jobs.submit(itemApi.reorganize(props.items.map((item) => item.id), choices), t("jobs.kind.reorganize"));
    emit("done", job.result as Record<string, number>);
  } catch (reason) {
    error.value = (reason as ApiError).detail ?? String(reason);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <VDialog :model-value="true" max-width="480" @update:model-value="(open) => !open && emit('close')">
    <VCard class="pa-2">
      <VCardTitle>{{ t("history.reorganizeTitle", { count: items.length }) }}</VCardTitle>
      <VCardText class="d-flex flex-column ga-4">
        <VAlert type="info" variant="tonal" density="compact" rounded="lg">{{ t("history.reorganizeNote") }}</VAlert>
        <VTextField v-model="form.title" :label="t('review.title')" :placeholder="String(first.plan.series ?? '')" persistent-placeholder
          hide-details />
        <VTextField v-if="kind === 'manga'" v-model="form.edition" :label="t('review.edition')" :placeholder="t('history.keep')" persistent-placeholder
          hide-details />
        <VTextField v-model="form.bgm" label="Bangumi" inputmode="numeric" :placeholder="String(first.subject_id ?? '')"
          persistent-placeholder :error-messages="badBgm ? t('history.badBgm') : undefined" hide-details="auto" />
        <VTextField v-if="single" v-model="form.volume" :label="t('history.volume')" :placeholder="t('history.keep')"
          persistent-placeholder :error-messages="badVolume ? t(kind === 'novel' ? 'review.badVolumeNovel' : 'review.badVolume') : undefined" hide-details="auto" />
        <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg">{{ error }}</VAlert>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="emit('close')">{{ t("common.cancel") }}</VBtn>
        <VBtn color="primary" variant="flat" data-test="reorganize-submit" :loading="busy" :disabled="busy || badVolume || badBgm"
          @click="submit">
{{ t("history.reorganize") }}
</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { items as itemApi, type Choices, type Item } from "@/api";
import type { ApiError } from "@/api/client";
import { isVolumeText, subjectRefOf } from "@/composables/volume";
import { useJobs } from "@/stores/jobs";
import { useAuth } from "@/stores/auth";
import { useLibraries } from "@/stores/libraries";

const props = defineProps<{ items: Item[] }>();
const emit = defineEmits<{ close: []; done: [result: Record<string, number>] }>();
const { t } = useI18n();
const jobs = useJobs();
const libraries = useLibraries();
const auth = useAuth();
const form = reactive({ title: "", edition: "", subject: "", volume: "" });
const busy = ref(false);
const error = ref("");
const single = computed(() => props.items.length === 1);
const first = computed(() => props.items[0]);
const kind = computed(() => libraries.kindOf(first.value.library_id));
const badVolume = computed(() => Boolean(form.volume.trim()) && !isVolumeText(form.volume, kind.value));
// A typed number is an id in the source the item already comes from; a pasted link names its own source.
const subject = computed(() => subjectRefOf(form.subject, first.value.subject_source ?? "bangumi"));
const badSubject = computed(() => Boolean(form.subject.trim()) && !subject.value);

async function submit() {
  const choices: Choices = {};
  if (form.title.trim()) choices.title = form.title.trim();
  if (form.edition.trim()) choices.edition = form.edition.trim();
  if (subject.value) choices.subject = subject.value;
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
        <VAlert :type="auth.desktop ? 'info' : 'warning'" variant="tonal" density="compact" rounded="lg" data-test="reorganize-note">
          {{ t(auth.desktop ? "history.reorganizeNoteDesktop" : "history.reorganizeNote") }}
        </VAlert>
        <VTextField v-model="form.title" :label="t('review.title')" :placeholder="String(first.plan.series ?? '')" persistent-placeholder
          hide-details />
        <VTextField v-if="kind === 'manga'" v-model="form.edition" :label="t('review.edition')" :placeholder="t('history.keep')" persistent-placeholder
          hide-details />
        <VTextField v-model="form.subject" :label="t('review.subject')" :placeholder="String(first.subject_id ?? '')"
          persistent-placeholder :error-messages="badSubject ? t('review.badSubject') : undefined" hide-details="auto"
          data-test="reorganize-subject" />
        <VTextField v-if="single" v-model="form.volume" :label="t('history.volume')" :placeholder="t('history.keep')"
          persistent-placeholder :error-messages="badVolume ? t(kind === 'novel' ? 'review.badVolumeNovel' : 'review.badVolume') : undefined" hide-details="auto" />
        <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg">{{ error }}</VAlert>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="emit('close')">{{ t("common.cancel") }}</VBtn>
        <VBtn color="primary" variant="flat" data-test="reorganize-submit" :loading="busy" :disabled="busy || badVolume || badSubject"
          @click="submit">
{{ t("history.reorganize") }}
</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

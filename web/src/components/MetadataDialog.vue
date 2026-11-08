<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { items as itemApi, type Item, type MetadataFields, type Subject, type SubjectRef } from "@/api";
import { sameSubject } from "@/composables/volume";
import type { ApiError } from "@/api/client";
import { useJobs } from "@/stores/jobs";
import SubjectCandidate from "./SubjectCandidate.vue";
import SubjectSearch from "./SubjectSearch.vue";

const props = defineProps<{ items: Item[]; kind: "manga" | "novel"; title: string }>();
const emit = defineEmits<{ close: []; done: [result: Record<string, number>] }>();
const { t } = useI18n();
const jobs = useJobs();

const DATE = /^\d{4}(-\d{1,2}(-\d{1,2})?)?$/;
const known = computed(() => (props.items[0]?.plan?.metadata ?? {}) as Record<string, unknown>);
// Books without a subject are the ones to fill in by hand; the others most likely need another subject.
const tab = ref<"source" | "manual">(props.items.some((item) => item.subject_id) ? "source" : "manual");
const candidates = ref<Subject[]>([]);
const picked = ref<SubjectRef | null>(null);
const busy = ref(false);
const error = ref("");

function text(key: string) {
  const value = known.value[key];
  return typeof value === "string" ? value : "";
}

function list(key: string) {
  const value = known.value[key];
  return Array.isArray(value) ? value.join("、") : "";
}

const novel = props.kind === "novel";
const form = reactive({
  localized_series: text("localized_series"),
  writers: list(novel ? "authors" : "writers"),
  illustrators: list("illustrators"),
  publisher: text("publisher"),
  release_date: text(novel ? "date" : "release_date"),
  genres: list("genres"),
  summary: text(novel ? "description" : "summary"),
});

const badDate = computed(() => Boolean(form.release_date.trim()) && !DATE.test(form.release_date.trim()));
const empty = computed(() => Object.values(form).every((value) => !value.trim()));
const ready = computed(() => (tab.value === "source" ? picked.value !== null : !empty.value && !badDate.value));

function names(value: string) {
  return value.split(/[,，、;；]/).map((name) => name.trim()).filter(Boolean);
}

async function submit() {
  const choice: { subject: SubjectRef } | { fields: MetadataFields } = tab.value === "source"
    ? { subject: picked.value as SubjectRef }
    : { fields: { localized_series: novel ? "" : form.localized_series.trim(), writers: names(form.writers),
      publisher: form.publisher.trim(), release_date: form.release_date.trim(), genres: names(form.genres),
      summary: form.summary.trim(), ...(novel ? { illustrators: names(form.illustrators) } : {}) } };
  busy.value = true;
  error.value = "";
  try {
    const job = await jobs.submit(itemApi.editMetadata(props.items.map((item) => item.id), choice), t("jobs.kind.metadata"));
    emit("done", job.result as Record<string, number>);
  } catch (reason) {
    error.value = (reason as ApiError).detail ?? String(reason);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <VDialog :model-value="true" max-width="640" scrollable @update:model-value="(open) => !open && emit('close')">
    <VCard class="pa-2" data-test="metadata-dialog">
      <VCardTitle>{{ t("history.metadataTitle", { count: items.length }) }}</VCardTitle>
      <VTabs v-model="tab" color="primary" density="compact" class="px-4">
        <VTab value="source" data-test="tab-source">{{ t("history.metadataSource") }}</VTab>
        <VTab value="manual" data-test="tab-manual">{{ t("history.metadataManual") }}</VTab>
      </VTabs>
      <VCardText class="d-flex flex-column ga-3 body">
        <VAlert type="info" variant="tonal" density="compact" rounded="lg">{{ t("history.metadataNote") }}</VAlert>
        <template v-if="tab === 'source'">
          <SubjectSearch :kind="kind" :initial="title" @results="candidates = $event" @error="error = $event" />
          <div v-if="candidates.length" class="candidates" role="radiogroup">
            <SubjectCandidate v-for="entry in candidates" :key="`${entry.source}:${entry.subject_id}`" :subject="entry"
              :selected="sameSubject(picked, { source: entry.source, id: entry.subject_id })"
              @pick="picked = { source: entry.source, id: entry.subject_id }" />
          </div>
        </template>
        <template v-else>
          <VTextField v-if="!novel" v-model="form.localized_series" :label="t('history.fields.localized')" hide-details
            data-test="field-localized" />
          <VTextField v-model="form.writers" :label="t('history.fields.writers')" :hint="t('history.fields.listHint')"
            persistent-hint data-test="field-writers" />
          <VTextField v-if="novel" v-model="form.illustrators" :label="t('history.fields.illustrators')"
            :hint="t('history.fields.listHint')" persistent-hint data-test="field-illustrators" />
          <div class="pair">
            <VTextField v-model="form.publisher" :label="t('history.fields.publisher')" hide-details data-test="field-publisher" />
            <VTextField v-model="form.release_date" :label="t('history.fields.date')" placeholder="2016-08"
              :error-messages="badDate ? t('history.fields.badDate') : undefined" hide-details="auto" data-test="field-date" />
          </div>
          <VTextField v-model="form.genres" :label="t('history.fields.genres')" :hint="t('history.fields.listHint')"
            persistent-hint data-test="field-genres" />
          <VTextarea v-model="form.summary" :label="t('history.fields.summary')" rows="4" auto-grow hide-details
            data-test="field-summary" />
        </template>
        <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg">{{ error }}</VAlert>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="emit('close')">{{ t("common.cancel") }}</VBtn>
        <VBtn color="primary" variant="flat" data-test="metadata-submit" :loading="busy" :disabled="busy || !ready"
          @click="submit">
{{ t("history.metadataSave") }}
</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.body { min-height: 320px; }
.candidates { display: flex; flex-direction: column; gap: 8px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 599px) {
  .pair { grid-template-columns: 1fr; }
}
</style>

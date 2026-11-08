<script setup lang="ts">
import { mdiCheck, mdiFastForward, mdiRefresh, mdiRobotOutline, mdiSkipNext } from "@mdi/js";
import { computed, nextTick, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { history, metadata, type Choices, type ReviewGroup, type Subject, type SubjectRef } from "@/api";
import { isVolumeText, sameSubject, sourceLabel, subjectRefOf } from "@/composables/volume";
import SubjectCandidate from "./SubjectCandidate.vue";
import SubjectSearch from "./SubjectSearch.vue";

const CANDIDATES = 8;
const LISTED_ITEMS = 200;

interface FileRow { id: number; name: string; work: string; guess: string }

/** What the AI last said about the group: its reading of the name, or its pick among a source's candidates. */
interface AiSuggestion {
  title: string | null;
  edition: string | null;
  subject_id: string | number | null;
  confidence: number;
  reason: string;
  problem: string | null;
}

const props = defineProps<{ group: ReviewGroup; kind: "manga" | "novel"; editions: string[]; aiReady: boolean; busy: boolean }>();
const emit = defineEmits<{ confirm: [choices: Choices, ids: number[]]; skip: []; reidentify: [] }>();
const { t } = useI18n();

const form = reactive({ title: "", edition: "", subject: null as SubjectRef | null });
/** What is in the subject box: a number (in the source picked above the candidates) or a pasted link. */
const subjectText = ref("");
const source = ref("bangumi");
const volumes = ref<Record<string, string>>({});
const files = ref<FileRow[]>([]);
const ticked = ref(new Set<number>());
const fileFilter = ref("");
const searchFor = ref("");
const search = ref<InstanceType<typeof SubjectSearch> | null>(null);
let titleTyped = false;
const candidates = ref<Subject[]>([]);
const suggestion = ref<AiSuggestion | null>(null);
const error = ref("");
const cache = new Map<string, Subject>();

const isNovel = computed(() => props.kind === "novel");
const shown = computed(() => {
  const wanted = fileFilter.value.trim().toLowerCase();
  return wanted ? files.value.filter((file) => file.name.toLowerCase().includes(wanted)) : files.value;
});
// Nothing listed (yet, or it could not be loaded) means the whole group.
const allTicked = computed(() => !files.value.length || ticked.value.size === files.value.length);
const noneTicked = computed(() => files.value.length > 0 && ticked.value.size === 0);
const typedVolumes = computed(() => Object.fromEntries(Object.entries(volumes.value)
  .filter(([id, value]) => value.trim() && (allTicked.value || ticked.value.has(Number(id))))));
const badVolume = computed(() => Object.values(typedVolumes.value).some((value) => !isVolumeText(value, props.kind)));
const hasChoice = computed(() => !noneTicked.value && Boolean(form.title.trim() || form.subject || Object.keys(typedVolumes.value).length));
const badSubject = computed(() => Boolean(subjectText.value.trim()) && !form.subject);
/** The works the AI read in this folder, when it read more than one. */
const works = computed(() => {
  const counts = new Map<string, number>();
  for (const file of files.value) if (file.work) counts.set(file.work, (counts.get(file.work) ?? 0) + 1);
  return counts.size > 1 ? [...counts].map(([title, count]) => ({ title, count })) : [];
});
function setSubjectText(value: string | null) {
  const ref = (value ?? "").trim() ? subjectRefOf(value ?? "", source.value) : null;
  form.subject = ref;
  // A pasted link becomes its id; the box's prefix names the source it belongs to.
  subjectText.value = ref ? ref.id : (value ?? "");
}

function choose(ref: SubjectRef | null) {
  form.subject = ref;
  subjectText.value = ref ? ref.id : "";
}

function toggle(id: number, on: boolean | null) {
  const next = new Set(ticked.value);
  if (on) next.add(id);
  else next.delete(id);
  ticked.value = next;
}

function tickAll() {
  ticked.value = new Set(files.value.map((file) => file.id));
}

function tickShown() {
  ticked.value = new Set(shown.value.map((file) => file.id));
}

async function pickWork(title: string) {
  ticked.value = new Set(files.value.filter((file) => file.work === title).map((file) => file.id));
  form.title = title;
  choose(null);
  titleTyped = false;
  searchFor.value = title;
  await nextTick();
  search.value?.search();
}

function guessOf(volume: unknown): string {
  const [kind, value] = String(volume ?? "").split(":");
  if (kind === "volume") return value ?? "";
  if (kind === "chapter") return `Ch.${value ?? ""}`;
  if (kind === "special") return value ? `SP${value}` : "SP";
  return "";
}

async function subject(ref: SubjectRef): Promise<Subject | null> {
  const key = `${ref.source}:${ref.id}`;
  if (cache.has(key)) return cache.get(key)!;
  try {
    const found = await metadata.subject(ref);
    cache.set(key, found);
    return found;
  } catch {
    return null;
  }
}

async function reset(group: ReviewGroup) {
  form.title = group.title_hint;
  form.edition = group.edition ?? "";
  choose(null);
  volumes.value = {};
  error.value = "";
  suggestion.value = (group.ai_suggestion as AiSuggestion | null) ?? null;
  candidates.value = [];
  files.value = [];
  ticked.value = new Set();
  fileFilter.value = "";
  searchFor.value = group.title_hint;
  titleTyped = false;
  const found = await Promise.all(group.candidates.slice(0, CANDIDATES).map(subject));
  if (props.group.key === group.key) candidates.value = found.filter((entry): entry is Subject => entry !== null);
  // One request for the whole folder, not one per volume (a chapter folder has hundreds).
  const loaded = await history.items(group.library_id, group.folder, "needs_review").catch(() => []);
  if (props.group.key === group.key) {
    files.value = loaded.slice(0, LISTED_ITEMS).map((item) => ({
      id: item.id, name: item.source_name, work: String(item.parsed?.title_hint ?? ""), guess: guessOf(item.parsed?.volume),
    }));
    tickAll();
  }
}

// By key and size: a background reload hands over new objects for the same group and must not wipe the form,
// but when some files were just confirmed what is left starts over.
watch(() => `${props.group.key}|${props.group.count}`, () => reset(props.group), { immediate: true });

function pick(entry: Subject) {
  choose({ source: entry.source, id: entry.subject_id });
  if (!titleTyped) form.title = entry.name_cn || entry.aliases[0] || entry.name;
}

function adopt() {
  if (!suggestion.value) return;
  if (suggestion.value.title) form.title = suggestion.value.title;
  if (suggestion.value.edition && !isNovel.value) form.edition = suggestion.value.edition;
  const id = suggestion.value.subject_id;
  if (id) {
    // The AI picks among the candidates it was shown: the review lists them, its pick first.
    const ref = props.group.candidates.find((entry) => entry.id === String(id)) ?? { source: source.value, id: String(id) };
    choose(ref);
  }
}

function chosenIds(): number[] {
  return allTicked.value ? props.group.item_ids : files.value.filter((file) => ticked.value.has(file.id)).map((file) => file.id);
}

function submit() {
  const choices: Choices = {};
  const title = form.title.trim();
  const typed = typedVolumes.value;
  // Part of a folder, or a folder of several works: the group's title says nothing about these files.
  const mustName = !allTicked.value || works.value.length > 0;
  if (title && (title !== props.group.title_hint || mustName || (!form.subject && !Object.keys(typed).length))) choices.title = title;
  if (!isNovel.value && form.edition.trim() && form.edition.trim() !== (props.group.edition ?? "")) choices.edition = form.edition.trim();
  if (form.subject) choices.subject = form.subject;
  if (Object.keys(typed).length) choices.volumes = typed;
  emit("confirm", choices, chosenIds());
}

function skipMetadata() {
  const choices: Choices = { title: form.title.trim(), skip_metadata: true };
  if (!isNovel.value && form.edition.trim()) choices.edition = form.edition.trim();
  if (Object.keys(typedVolumes.value).length) choices.volumes = typedVolumes.value;
  emit("confirm", choices, chosenIds());
}
</script>

<template>
  <VCard data-test="detail" class="detail">
    <div class="d-flex align-start ga-3 flex-wrap">
      <div class="min-w-0">
        <div class="st-muted text-caption">{{ t("review.folder") }}</div>
        <h2 class="folder">{{ group.folder }}</h2>
      </div>
      <VSpacer />
      <VChip v-for="entry in group.reasons" :key="entry" size="small" color="warning" variant="tonal">{{ t(`reason.${entry}`) }}</VChip>
      <VChip size="small" variant="tonal">{{ t("review.count", { count: group.count }) }}</VChip>
    </div>
    <div class="section-title">{{ t("review.candidates") }}</div>
    <SubjectSearch ref="search" :key="group.key" v-model:source="source" :kind="kind" :initial="searchFor"
      @results="candidates = $event" @error="error = $event" />
    <div class="candidates" role="radiogroup" :aria-label="t('review.candidates')">
      <SubjectCandidate v-for="entry in candidates" :key="`${entry.source}:${entry.subject_id}`" :subject="entry"
        :selected="sameSubject(form.subject, { source: entry.source, id: entry.subject_id })"
        @pick="pick(entry)" />
      <div v-if="!candidates.length" class="st-muted text-body-2">{{ t("review.noCandidates") }}</div>
    </div>

    <div class="section-title">{{ t("review.confirmAs") }}</div>
    <div class="fields" :class="{ 'fields-novel': isNovel }">
      <VTextField v-model="form.title" :label="t('review.title')" hide-details data-test="title" @update:model-value="titleTyped = true" />
      <VCombobox v-if="!isNovel" v-model="form.edition" :items="editions" :label="t('review.edition')" :placeholder="t('review.noEdition')"
        clearable hide-details="auto" :hint="t('review.customEdition')" data-test="edition"
        @update:model-value="(value: string | null) => (form.edition = value ?? '')" />
      <VTextField :model-value="subjectText" :label="t('review.subject')" hide-details="auto" data-test="subject"
        :prefix="form.subject ? sourceLabel(form.subject.source) : undefined"
        :error-messages="badSubject ? t('review.badSubject') : undefined" @update:model-value="setSubjectText" />
    </div>

    <div class="section-title">{{ t("review.files") }}</div>
    <div v-if="files.length > 1" class="st-muted text-body-2 mb-3">{{ t("review.partHint") }}</div>
    <div v-if="works.length" class="works">
      <span class="st-muted text-body-2">{{ t("review.aiWorks") }}</span>
      <VChip v-for="work in works" :key="work.title" size="small" variant="tonal" color="primary" data-test="ai-work" @click="pickWork(work.title)">
        {{ work.title }} {{ work.count }}
      </VChip>
    </div>
    <div v-if="files.length > 1" class="file-tools">
      <VTextField v-model="fileFilter" density="compact" hide-details clearable :placeholder="t('review.filterFiles')" data-test="file-filter"
        @click:clear="fileFilter = ''" />
      <VBtn size="small" variant="tonal" :disabled="!fileFilter.trim()" data-test="select-shown" @click="tickShown">{{ t("review.selectShown") }}</VBtn>
      <VBtn size="small" variant="text" data-test="select-all" @click="tickAll">{{ t("review.selectAll") }}</VBtn>
      <span class="st-muted text-body-2 nowrap">{{ t("review.selected", { selected: ticked.size, total: files.length }) }}</span>
    </div>
    <div v-for="file in shown" :key="file.id" class="file" data-test="file-row">
      <VCheckbox :model-value="ticked.has(file.id)" density="compact" hide-details data-test="file-check" class="file-check"
        :aria-label="file.name" @update:model-value="toggle(file.id, $event)" />
      <span class="file-name">{{ file.name }}</span>
      <VTextField v-model="volumes[String(file.id)]" density="compact" hide-details :placeholder="file.guess || '13'" class="volume-input"
        data-test="volume" />
    </div>
    <div v-if="files.length" class="st-muted text-caption mt-2">{{ t(isNovel ? "review.volumeHintNovel" : "review.volumeHint") }}</div>
    <div v-if="group.count > files.length && files.length" class="st-muted text-caption mt-1">
      {{ t("review.volumesMore", { shown: files.length, total: group.count }) }}
    </div>
    <div v-if="badVolume" class="text-error text-body-2 mt-2">{{ t(isNovel ? "review.badVolumeNovel" : "review.badVolume") }}</div>

    <VAlert v-if="suggestion" :type="suggestion.problem ? 'warning' : 'info'" variant="tonal" rounded="lg" class="mt-4"
      :icon="mdiRobotOutline">
      <template v-if="suggestion.problem">{{ t("review.aiProblem", { problem: suggestion.problem }) }}</template>
      <template v-else>
        {{ isNovel
          ? t("review.aiSuggestsNovel", { title: suggestion.title ?? "—", subject: suggestion.subject_id ?? "—", confidence: suggestion.confidence.toFixed(2) })
          : t("review.aiSuggests", { title: suggestion.title ?? "—", edition: suggestion.edition ?? t("review.noEdition"),
              subject: suggestion.subject_id ?? "—", confidence: suggestion.confidence.toFixed(2) }) }}
        <div class="reason">{{ suggestion.reason }}</div>
        <VBtn size="small" variant="tonal" class="mt-2" @click="adopt">{{ t("review.adopt") }}</VBtn>
      </template>
    </VAlert>
    <VAlert v-if="error" type="error" variant="tonal" rounded="lg" density="compact" class="mt-4">{{ error }}</VAlert>

    <div class="actions">
      <div class="aside">
        <VBtn v-if="!aiReady" variant="text" color="primary" :to="{ name: 'settings', params: { tab: 'ai' } }" data-test="setup-ai">
          {{ t("review.setupAi") }}
        </VBtn>
        <VBtn variant="text" :prepend-icon="mdiRefresh" :disabled="busy || !aiReady" data-test="reidentify-group" @click="emit('reidentify')">
          {{ t("review.reidentifyGroup") }}
        </VBtn>
        <VBtn variant="text" :prepend-icon="mdiSkipNext" :disabled="busy" @click="emit('skip')">{{ t("review.skip") }}</VBtn>
      </div>
      <div class="decide">
        <VBtn variant="tonal" color="primary" :prepend-icon="mdiFastForward" data-test="skip-metadata" :title="t('review.skipMetadataHint')"
          :disabled="busy || !form.title.trim() || badVolume || noneTicked" @click="skipMetadata">
          {{ t("review.skipMetadata") }}
        </VBtn>
        <VBtn color="primary" :prepend-icon="mdiCheck" data-test="confirm" :loading="busy" :disabled="busy || !hasChoice || badVolume || badSubject"
          @click="submit">
          {{ allTicked ? t("review.confirm") : t("review.confirmSelected", { count: ticked.size }) }}
        </VBtn>
      </div>
    </div>
  </VCard>
</template>

<style scoped>
.detail { padding: 20px 24px; }
.min-w-0 { min-width: 0; }
.folder { margin: 2px 0 0; word-break: break-all; font-size: 18px; font-weight: 600; }
.section-title { font-size: 13px; font-weight: 600; opacity: 0.7; margin: 22px 0 10px; }
.candidates { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin-top: 12px; }
.fields { display: grid; grid-template-columns: 2fr 1.5fr 1fr; gap: 12px; }
.fields-novel { grid-template-columns: 2fr 1fr; }
.works { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.file-tools { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.file-tools :deep(.v-input) { flex: 1; min-width: 180px; }
.nowrap { white-space: nowrap; }
.file { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.file-check { flex: none; }
.file-name { flex: 1; font-size: 13px; word-break: break-all; }
.volume-input { width: 96px; flex: none; }
.reason { font-size: 12px; opacity: 0.8; margin-top: 4px; }
.actions { display: flex; align-items: center; justify-content: space-between; gap: 8px 16px; margin-top: 24px; flex-wrap: wrap; }
.aside, .decide { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.decide { margin-left: auto; justify-content: flex-end; }
@media (max-width: 899px) {
  .fields, .fields-novel { grid-template-columns: minmax(0, 1fr); }
}
</style>

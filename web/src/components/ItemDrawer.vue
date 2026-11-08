<script setup lang="ts">
import { mdiClose } from "@mdi/js";
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useDisplay } from "vuetify";
import { items as itemApi, type ItemDetail } from "@/api";
import type { ApiError } from "@/api/client";
import { eventDetail } from "@/composables/eventDetail";
import { shortTime } from "@/composables/format";
import { sourceLabel, subjectUrl } from "@/composables/volume";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";
import ReorganizeDialog from "./ReorganizeDialog.vue";
import StatusTag from "./StatusTag.vue";

const props = defineProps<{ itemId: number | null }>();
const emit = defineEmits<{ close: []; changed: [] }>();
const { t, te } = useI18n();
const { smAndDown, width } = useDisplay();
const jobs = useJobs();
const libraries = useLibraries();
const item = ref<ItemDetail | null>(null);
const loading = ref(false);
const reorganizing = ref(false);
const drawerWidth = computed(() => (smAndDown.value ? width.value : 520));

async function load() {
  if (props.itemId === null) return;
  loading.value = true;
  try {
    item.value = await itemApi.get(props.itemId);
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    loading.value = false;
  }
}

watch(() => props.itemId, load, { immediate: true });

function eventName(kind: string) {
  return te(`event.${kind}`) ? t(`event.${kind}`) : kind;
}

async function run(kind: "retry" | "cancel") {
  if (!item.value) return;
  try {
    if (kind === "retry") await jobs.submit(itemApi.retry([item.value.id]), t("jobs.kind.retry"));
    else {
      await itemApi.cancel([item.value.id]);
      libraries.refresh().catch(() => {}); // cancelling is not a job, so nothing else refreshes the counts
    }
    emit("changed");
    await load();
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  }
}

async function reorganized(result: Record<string, number>) {
  reorganizing.value = false;
  if (result.skipped && !result.replanned) notify.warning(t("history.sourceGone"));
  else notify.success(t("history.reorganized"));
  emit("changed");
  await load();
}
</script>

<template>
  <VNavigationDrawer :model-value="itemId !== null" location="right" temporary :width="drawerWidth" class="drawer"
    disable-route-watcher data-test="item-drawer"
    @update:model-value="(open) => !open && emit('close')">
    <div class="head">
      <div class="text-subtitle-1 font-weight-bold name">{{ item?.source_name ?? "" }}</div>
      <VBtn icon variant="text" size="small" @click="emit('close')"><VIcon :icon="mdiClose" /></VBtn>
    </div>
    <VProgressLinear v-if="loading" indeterminate color="primary" />
    <div v-if="item" class="body">
      <dl class="facts">
        <dt>{{ t("history.status") }}</dt><dd><StatusTag :status="item.status" :reason="item.review_reason" /></dd>
        <dt>{{ t("history.source") }}</dt><dd>{{ item.source_path }}</dd>
        <dt>{{ t("history.target") }}</dt><dd>{{ item.target_path ?? "—" }}</dd>
        <dt>{{ t("history.subject") }}</dt>
        <dd data-test="item-subject">
          <template v-if="item.subject_id">
            {{ sourceLabel(item.subject_source ?? "bangumi") }}
            <a v-if="subjectUrl(item.subject_source, item.subject_id)" :href="subjectUrl(item.subject_source, item.subject_id)"
              target="_blank" rel="noopener">{{ item.subject_id }}</a>
            <template v-else>{{ item.subject_id }}</template>
          </template>
          <template v-else>—</template>
        </dd>
        <dt>{{ t("history.parsed") }}</dt>
        <dd>{{ [item.parsed.title_hint, item.parsed.edition, item.parsed.volume].filter(Boolean).join(" · ") || "—" }}</dd>
        <template v-if="item.error"><dt>{{ t("history.error") }}</dt><dd class="text-error">{{ item.error }}</dd></template>
      </dl>
      <div class="d-flex ga-2 flex-wrap my-4">
        <VBtn v-if="item.status === 'published'" variant="tonal" color="primary" size="small" data-test="reorganize"
          @click="reorganizing = true">
{{ t("history.reorganize") }}…
</VBtn>
        <VBtn v-if="['failed', 'duplicate', 'parsed', 'cancelled'].includes(item.status)" variant="tonal" size="small"
          @click="run('retry')">
{{ t("common.retry") }}
</VBtn>
        <VBtn v-if="['planned', 'ready', 'needs_review'].includes(item.status)" variant="tonal" size="small"
          @click="run('cancel')">
{{ t("common.cancel") }}
</VBtn>
      </div>
      <div class="section-title">{{ t("history.timeline") }}</div>
      <VTimeline side="end" density="compact" align="start" truncate-line="both" data-test="timeline">
        <VTimelineItem v-for="(event, index) in item.events" :key="index" size="x-small"
          :dot-color="event.kind === 'failed' ? 'error' : event.kind === 'published' ? 'success' : 'primary'">
          <div class="event-head">
            <strong>{{ eventName(event.kind) }}</strong>
            <span class="st-muted text-caption">{{ shortTime(event.at) }}</span>
          </div>
          <div v-if="eventDetail(event.detail)" class="event-detail">{{ eventDetail(event.detail) }}</div>
        </VTimelineItem>
      </VTimeline>
      <template v-if="item.ai_calls.length">
        <div class="section-title">{{ t("history.aiCalls") }}</div>
        <VExpansionPanels variant="accordion" flat>
          <VExpansionPanel v-for="call in item.ai_calls" :key="call.id"
            :title="`${call.purpose} · ${call.model} · ${shortTime(call.created_at)}`">
            <VExpansionPanelText><pre class="raw">{{ call.error ?? call.response_text }}</pre></VExpansionPanelText>
          </VExpansionPanel>
        </VExpansionPanels>
      </template>
    </div>
    <ReorganizeDialog v-if="reorganizing && item" :items="[item]" @close="reorganizing = false" @done="reorganized" />
  </VNavigationDrawer>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 8px; padding: 16px 12px 8px 20px; }
.name { flex: 1; min-width: 0; word-break: break-all; }
.body { padding: 4px 20px 24px; }
.facts { display: grid; grid-template-columns: 76px 1fr; gap: 8px 12px; margin: 0; font-size: 13px; }
.facts dt { opacity: 0.6; }
.facts dd { margin: 0; word-break: break-all; }
.section-title { font-size: 13px; font-weight: 600; opacity: 0.7; margin: 16px 0 8px; }
.event-head { display: flex; gap: 8px; align-items: baseline; font-size: 13px; }
.event-detail { font-size: 12px; opacity: 0.75; word-break: break-all; }
.raw { white-space: pre-wrap; word-break: break-all; font-size: 12px; margin: 0; }
</style>

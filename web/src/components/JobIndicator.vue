<script setup lang="ts">
import { mdiClose } from "@mdi/js";
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

interface Progress {
  done: number;
  total: number;
  current?: string | null;
}

const { t } = useI18n();
const jobs = useJobs();
const libraries = useLibraries();

const first = computed(() => jobs.running[0]);
const progress = computed(() => {
  const value = first.value?.progress as Progress | null | undefined;
  return value && value.total > 0 ? value : null;
});
const percent = computed(() => (progress.value ? Math.floor((Math.min(progress.value.done, progress.value.total) * 100) / progress.value.total) : 0));
// A scan started in another tab or by the watcher has no label here: name it by its library.
const label = computed(() => {
  const job = first.value;
  if (!job) return "";
  if (job.label) return job.label;
  const library = libraries.list.find((entry) => entry.id === job.library_id);
  return job.kind === "scan" && library ? t("jobs.scanOf", { name: library.name }) : t(`jobs.kind.${job.kind}`);
});
</script>

<template>
  <VTooltip v-if="first" location="bottom" :disabled="!progress?.current">
    <template #activator="{ props: tip }">
      <VChip v-bind="tip" color="primary" variant="tonal" class="mr-2" data-test="job-indicator">
        <VProgressCircular v-if="progress" :model-value="percent" size="16" width="3" class="mr-2"
          data-test="job-progress" />
        <VProgressCircular v-else indeterminate size="14" width="2" class="mr-2" />
        {{ t("jobs.running", { label, more: jobs.running.length - 1 }, jobs.running.length) }}
        <span v-if="progress" class="count">{{ progress.done }} / {{ progress.total }}</span>
        <span v-if="first.cancelling" class="count" data-test="job-stopping">{{ t("jobs.stopping") }}</span>
        <button v-else type="button" class="stop" :aria-label="t('jobs.stop')" :title="t('jobs.stop')"
          data-test="job-stop" @click.stop="jobs.cancel(first!.id)">
          <VIcon :icon="mdiClose" size="14" />
        </button>
      </VChip>
    </template>
    {{ t("jobs.current", { name: progress?.current }) }}
  </VTooltip>
</template>

<style scoped>
.count { margin-left: 8px; font-variant-numeric: tabular-nums; opacity: 0.8; }
.stop { display: inline-flex; margin-left: 6px; margin-right: -4px; padding: 2px; border-radius: 50%; color: inherit; cursor: pointer; }
.stop:hover, .stop:focus-visible { background: rgba(var(--v-theme-primary), 0.2); }
</style>

<script setup lang="ts">
import { mdiCheckCircle, mdiOpenInNew } from "@mdi/js";
import { ref } from "vue";
import type { Subject } from "@/api";
import { sourceLabel } from "@/composables/volume";

defineProps<{ subject: Subject; selected: boolean }>();
const emit = defineEmits<{ pick: [] }>();
const broken = ref(false);
</script>

<template>
  <div data-test="candidate" class="candidate" :class="{ selected }" role="radio" :aria-checked="selected" tabindex="0"
    @click="emit('pick')" @keydown.enter.prevent="emit('pick')" @keydown.space.prevent="emit('pick')">
    <div class="cover">
      <img v-if="subject.image && !broken" :src="subject.image" alt="" loading="lazy" referrerpolicy="no-referrer"
        @error="broken = true" />
    </div>
    <div class="info">
      <strong class="name">{{ subject.name_cn || subject.aliases[0] || subject.name }}</strong>
      <span class="line">{{ subject.name }}</span>
      <span class="line">
        {{ [subject.writers.join("、"), subject.publisher, subject.platform, subject.release_date?.slice(0, 4)].filter(Boolean).join(" · ") }}
      </span>
      <span class="line"><span class="source" data-test="candidate-source">{{ sourceLabel(subject.source) }}</span> #{{ subject.subject_id }}<template v-if="subject.total_volumes"> · {{ $t("review.volumes", { count: subject.total_volumes }) }}</template></span>
    </div>
    <a v-if="subject.web_url" :href="subject.web_url" target="_blank" rel="noopener noreferrer" class="open"
      :title="$t('review.openSource', { source: sourceLabel(subject.source) })"
      :aria-label="$t('review.openSource', { source: sourceLabel(subject.source) })" data-test="candidate-open"
      @click.stop @keydown.stop>
      <VIcon :icon="mdiOpenInNew" size="16" />
    </a>
    <VIcon v-if="selected" :icon="mdiCheckCircle" color="primary" size="20" class="check" />
  </div>
</template>

<style scoped>
.candidate {
  position: relative; display: flex; gap: 12px; padding: 10px; border-radius: 12px; cursor: pointer;
  border: 1.5px solid rgba(var(--v-border-color), var(--v-border-opacity)); transition: border-color 0.15s, background 0.15s;
}
.candidate:hover { background: rgba(var(--v-theme-primary), 0.04); }
.candidate:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }
.candidate.selected { border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.06); }
.cover { width: 52px; height: 72px; flex: none; border-radius: 8px; overflow: hidden; background: rgba(var(--v-theme-on-surface), 0.08); }
.cover img { width: 100%; height: 100%; object-fit: cover; }
.info { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 20px; }
.line { font-size: 12px; opacity: 0.65; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source { font-weight: 600; }
.check { position: absolute; top: 8px; right: 8px; }
.open {
  position: absolute; right: 6px; bottom: 6px; display: grid; place-items: center; width: 28px; height: 28px;
  border-radius: 8px; color: rgb(var(--v-theme-on-surface)); opacity: 0.5; transition: opacity 0.15s, background 0.15s;
}
.open:hover, .open:focus-visible { opacity: 1; background: rgba(var(--v-theme-primary), 0.1); color: rgb(var(--v-theme-primary)); }
</style>

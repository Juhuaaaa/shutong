<script setup lang="ts">
import { mdiClose, mdiContentCut, mdiImageBroken } from "@mdi/js";
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { items as itemApi, type Item } from "@/api";
import type { ApiError } from "@/api/client";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";
import CoverPicker from "./CoverPicker.vue";

const WIDTH = 240;
const props = defineProps<{ items: Item[]; title: string }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const jobs = useJobs();
const stamp = ref(Date.now());
const picking = ref<Item | null>(null);
const busy = ref(false);
const broken = ref(new Set<number>());

const volumes = computed(() => props.items.filter((item) => item.status === "published"));

function nameOf(item: Item) {
  return item.target_path?.split("/").pop()?.replace(/\.[^.]+$/, "") ?? String(item.id);
}

function reload() {
  broken.value = new Set();
  stamp.value = Date.now();
}

function missing(id: number) {
  broken.value = new Set(broken.value).add(id);
}

function chosen() {
  picking.value = null;
  reload();
  notify.success(t("covers.saved"));
}

async function cropJackets() {
  busy.value = true;
  try {
    const job = await jobs.submit(itemApi.cropJackets(volumes.value.map((item) => item.id)), t("jobs.kind.cover"));
    const result = job.result as Record<string, number>;
    const counts = { cropped: result.cropped ?? 0, skipped: result.skipped ?? 0, failed: result.failed ?? 0 };
    if (counts.failed) notify.warning(t("covers.croppedPartly", counts));
    else notify.success(t("covers.cropped", counts));
    reload();
  } catch (error) {
    notify.error((error as ApiError).detail ?? String(error));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <VDialog :model-value="true" max-width="1180" scrollable @update:model-value="(open) => !open && emit('close')">
    <VCard data-test="cover-wall">
      <div class="head">
        <div class="text-subtitle-1 font-weight-bold title">{{ t("covers.title", { title }) }}</div>
        <VSpacer />
        <VBtn size="small" variant="tonal" color="primary" :prepend-icon="mdiContentCut" :loading="busy"
          :title="t('covers.cropJacketsHint')" data-test="crop-jackets" @click="cropJackets">
          {{ t("covers.cropJackets") }}
        </VBtn>
        <VBtn icon variant="text" size="small" :aria-label="t('common.close')" data-test="wall-close" @click="emit('close')">
          <VIcon :icon="mdiClose" />
        </VBtn>
      </div>
      <VCardText class="wall">
        <div v-if="!volumes.length" class="st-muted">{{ t("covers.empty") }}</div>
        <button v-for="item in volumes" :key="item.id" type="button" class="volume" data-test="wall-volume" @click="picking = item">
          <span class="image">
            <img v-if="!broken.has(item.id)" :src="itemApi.coverUrl(item.id, WIDTH, stamp)" :alt="nameOf(item)" loading="lazy"
              @error="missing(item.id)" />
            <span v-else class="missing"><VIcon :icon="mdiImageBroken" /> {{ t("covers.noImage") }}</span>
          </span>
          <span class="name" :title="nameOf(item)">{{ nameOf(item) }}</span>
        </button>
      </VCardText>
    </VCard>
    <CoverPicker v-if="picking" :item="picking" :name="nameOf(picking)" @close="picking = null" @chosen="chosen" />
  </VDialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 8px; padding: 14px 16px 14px 24px; }
.title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wall { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 16px; }
.volume { display: flex; flex-direction: column; gap: 6px; padding: 0; background: none; border: 0; cursor: pointer; color: inherit; text-align: left; min-width: 0; }
.image { display: block; aspect-ratio: 2 / 3; border-radius: 6px; overflow: hidden; background: rgba(var(--v-border-color), 0.08); transition: outline-color 0.15s; outline: 2px solid transparent; }
.volume:hover .image, .volume:focus-visible .image { outline-color: rgb(var(--v-theme-primary)); }
.image img { display: block; width: 100%; height: 100%; object-fit: cover; }
.missing { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 4px; font-size: 12px; opacity: 0.6; }
.name { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>

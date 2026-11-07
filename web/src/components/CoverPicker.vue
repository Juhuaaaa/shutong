<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { items as itemApi, type Item } from "@/api";
import type { ApiError } from "@/api/client";
import { useJobs } from "@/stores/jobs";

const PAGES = 40;
const props = defineProps<{ item: Item; name: string }>();
const emit = defineEmits<{ close: []; chosen: [] }>();
const { t } = useI18n();
const jobs = useJobs();
const stamp = String(props.item.updated_at);

const pages = ref<string[]>([]);
const current = ref<string | null>(null);
const added = ref(false);
const picked = ref<string | null>(null);
const cropping = ref(false);
const range = ref<[number, number]>([0, 100]);
const jacketFound = ref(false);
const loading = ref(true);
const busy = ref(false);
const error = ref("");

const shown = computed(() => pages.value.slice(0, PAGES));
const keep = computed(() => ({ left: `${range.value[0]}%`, width: `${range.value[1] - range.value[0]}%` }));

onMounted(async () => {
  try {
    const options = await itemApi.coverOptions(props.item.id);
    pages.value = options.pages;
    current.value = options.current;
    added.value = options.added;
    picked.value = options.current ?? options.pages[0] ?? null;
    if (options.jacket) {
      picked.value = options.jacket.page;
      cropping.value = true;
      jacketFound.value = true;
      range.value = [Math.round(options.jacket.left * 1000) / 10, Math.round(options.jacket.right * 1000) / 10];
    }
  } catch (reason) {
    error.value = (reason as ApiError).detail ?? String(reason);
  } finally {
    loading.value = false;
  }
});

function pick(page: string) {
  picked.value = page;
  jacketFound.value = false;
  cropping.value = false;
  range.value = [0, 100];
}

async function apply(choice: { page: string; left?: number; right?: number }) {
  busy.value = true;
  error.value = "";
  try {
    await jobs.submit(itemApi.chooseCover(props.item.id, choice), t("jobs.kind.cover"));
    emit("chosen");
  } catch (reason) {
    error.value = (reason as ApiError).detail ?? String(reason);
  } finally {
    busy.value = false;
  }
}

function use() {
  if (!picked.value) return;
  apply(cropping.value ? { page: picked.value, left: range.value[0] / 100, right: range.value[1] / 100 } : { page: picked.value });
}
</script>

<template>
  <VDialog :model-value="true" max-width="860" scrollable @update:model-value="(open) => !open && emit('close')">
    <VCard data-test="cover-picker">
      <VCardTitle class="picker-title">{{ t("covers.pick", { name }) }}</VCardTitle>
      <VCardText>
        <VProgressLinear v-if="loading" indeterminate color="primary" />
        <div v-if="pages.length" class="st-muted text-body-2 mb-3">{{ t("covers.pickHint") }}</div>
        <div v-if="picked" class="preview">
          <div class="frame">
            <img :src="itemApi.coverUrl(item.id, 640, stamp, picked)" :alt="picked" />
            <template v-if="cropping">
              <span class="shade" :style="{ left: 0, width: `${range[0]}%` }" />
              <span class="shade" :style="{ left: `${range[1]}%`, right: 0 }" />
              <span class="keep" :style="keep" />
            </template>
          </div>
        </div>
        <div v-if="jacketFound" class="text-body-2 text-primary mt-2" data-test="jacket-found">{{ t("covers.jacketFound") }}</div>
        <div v-if="picked" class="crop">
          <VSwitch v-model="cropping" :label="t('covers.crop')" hide-details density="compact" data-test="crop-toggle" />
          <VRangeSlider v-if="cropping" v-model="range" :min="0" :max="100" :step="0.5" hide-details :label="t('covers.cropRange')"
            data-test="crop-range" />
        </div>
        <div class="pages" role="listbox">
          <button v-for="page in shown" :key="page" type="button" class="page" :class="{ on: page === picked }" role="option"
            :aria-selected="page === picked" data-test="cover-page" @click="pick(page)">
            <img :src="itemApi.coverUrl(item.id, 160, stamp, page)" :alt="page" loading="lazy" />
            <span v-if="page === current" class="tag">{{ t("covers.current") }}</span>
          </button>
        </div>
        <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg" class="mt-3">{{ error }}</VAlert>
      </VCardText>
      <VCardActions>
        <VBtn v-if="added && pages.length" variant="text" :disabled="busy" data-test="cover-restore" @click="apply({ page: pages[0] })">
          {{ t("covers.restore") }}
        </VBtn>
        <VSpacer />
        <VBtn variant="text" @click="emit('close')">{{ t("common.cancel") }}</VBtn>
        <VBtn color="primary" variant="flat" :disabled="!picked || busy" :loading="busy" data-test="cover-use" @click="use">{{ t("covers.use") }}</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.picker-title { overflow: hidden; text-overflow: ellipsis; }
.preview { display: flex; justify-content: center; }
.frame { position: relative; line-height: 0; max-width: 100%; }
.frame img { max-width: 100%; max-height: 340px; border-radius: 4px; }
.shade { position: absolute; top: 0; bottom: 0; background: rgba(0, 0, 0, 0.55); }
.keep { position: absolute; top: 0; bottom: 0; box-sizing: border-box; border: 2px solid rgb(var(--v-theme-primary)); }
.crop { display: flex; align-items: center; gap: 16px; margin-top: 8px; flex-wrap: wrap; }
.crop :deep(.v-range-slider) { flex: 1; min-width: 220px; }
.pages { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 10px; margin-top: 14px; }
.page { position: relative; padding: 0; background: none; border: 0; cursor: pointer; border-radius: 4px; overflow: hidden; outline: 2px solid transparent; aspect-ratio: 2 / 3; }
.page.on, .page:hover, .page:focus-visible { outline-color: rgb(var(--v-theme-primary)); }
.page img { display: block; width: 100%; height: 100%; object-fit: cover; }
.tag { position: absolute; left: 4px; top: 4px; padding: 0 5px; border-radius: 3px; font-size: 11px; line-height: 16px; color: #fff; background: rgb(var(--v-theme-primary)); }
</style>

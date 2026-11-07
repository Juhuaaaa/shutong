<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { desktop } from "@/api";
import { ApiError } from "@/api/client";
import { bridge } from "@/composables/desktop";
import { notify } from "@/composables/notify";
import { useJobs } from "@/stores/jobs";

const { t } = useI18n();
const router = useRouter();
const jobs = useJobs();
const ids = ref<number[]>([]);
const busy = ref(false);
const count = computed(() => ids.value.length);

async function refresh() {
  ids.value = (await desktop.originals()).items.map((item) => item.id);
}

function failed(error: unknown) {
  notify.error(error instanceof ApiError ? error.detail : String(error));
}

async function keep() {
  busy.value = true;
  try {
    await desktop.keep(ids.value);
    ids.value = [];
  } catch (error) {
    failed(error);
  } finally {
    busy.value = false;
  }
}

async function trash() {
  busy.value = true;
  try {
    const result = await bridge()!.trashOriginals([...ids.value]);
    if (result.trashed.length) notify.success(t("desktop.originals.trashed", { count: result.trashed.length }));
    if (result.failed.length) {
      notify.error(t("desktop.originals.failed", { count: result.failed.length, first: result.failed[0].error }));
    }
    await refresh();
  } catch (error) {
    failed(error);
  } finally {
    busy.value = false;
  }
}

onMounted(() => refresh().catch(() => {}));
watch(() => jobs.running.length, (now, before) => {
  if (now === 0 && before > 0) refresh().catch(() => {});
});
</script>

<template>
  <VAlert v-if="count" type="success" variant="tonal" rounded="lg" class="mb-4" data-test="originals-prompt">
    <div>{{ t("desktop.originals.text", { count }) }}</div>
    <div class="actions">
      <VBtn size="small" variant="text" data-test="originals-view" @click="router.push({ name: 'history' })">{{ t("desktop.originals.view") }}</VBtn>
      <VBtn size="small" variant="text" :disabled="busy" data-test="originals-keep" @click="keep">{{ t("desktop.originals.keep") }}</VBtn>
      <VBtn size="small" variant="tonal" color="primary" :loading="busy" data-test="originals-trash" @click="trash">{{ t("desktop.originals.trash") }}</VBtn>
    </div>
  </VAlert>
</template>

<style scoped>
.actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>

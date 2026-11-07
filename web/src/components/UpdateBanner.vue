<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { bridge } from "@/composables/desktop";

const { t } = useI18n();
const update = ref<{ version: string; url: string } | null>(null);
onMounted(() => bridge()?.onUpdate((info) => (update.value = info)));
</script>

<template>
  <VAlert v-if="update" type="info" variant="tonal" rounded="lg" density="compact" closable class="mb-4" data-test="update-banner">
    <div class="d-flex align-center flex-wrap ga-2">
      <span>{{ t("desktop.update.text", { version: update.version }) }}</span>
      <VBtn size="small" variant="text" data-test="update-download" @click="bridge()?.openExternal(update!.url)">{{ t("desktop.update.action") }}</VBtn>
    </div>
  </VAlert>
</template>

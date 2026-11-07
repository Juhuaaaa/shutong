<script setup lang="ts">
import { computed } from "vue";
import { dismiss, notifyState } from "@/composables/notify";

const current = computed(() => notifyState.queue[0]);
const icons = { success: "$success", error: "$error", info: "$info", warning: "$warning" } as const;
</script>

<template>
  <VSnackbar :key="current?.id" :model-value="!!current" :color="current?.kind" :timeout="current?.kind === 'error' ? 6000 : 3000"
    location="bottom" rounded="lg" @update:model-value="(open) => !open && dismiss()">
    <div v-if="current" class="d-flex align-center ga-2" data-test="notify">
      <VIcon :icon="icons[current.kind]" size="20" />
      <span>{{ current.text }}</span>
    </div>
  </VSnackbar>
</template>

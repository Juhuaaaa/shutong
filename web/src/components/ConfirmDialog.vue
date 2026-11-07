<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { answer, confirmState } from "@/composables/confirm";

const { t } = useI18n();
const current = computed(() => confirmState.queue[0]);
</script>

<template>
  <VDialog :model-value="!!current" max-width="440" @update:model-value="(open) => !open && answer(false)">
    <VCard v-if="current" data-test="confirm-dialog">
      <VCardTitle class="d-flex align-center ga-2 pt-5 px-6">
        <VIcon :icon="current.danger ? '$warning' : '$info'" :color="current.danger ? 'warning' : 'primary'" />
        {{ current.title }}
      </VCardTitle>
      <VCardText class="px-6 confirm-text">{{ current.text }}</VCardText>
      <VCardActions class="px-6 pb-5">
        <VSpacer />
        <VBtn variant="text" data-test="confirm-no" @click="answer(false)">{{ t("common.cancel") }}</VBtn>
        <VBtn :color="current.danger ? 'error' : 'primary'" variant="flat" data-test="confirm-yes" @click="answer(true)">
          {{ t("common.confirm") }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.confirm-text { white-space: pre-line; word-break: break-all; }
</style>

<script setup lang="ts">
import { mdiEye, mdiEyeOff } from "@mdi/js";
import { ref } from "vue";
import { useI18n } from "vue-i18n";

defineProps<{ label: string; isSet: boolean; hint?: string; clearTest?: string }>();
const model = defineModel<string>({ default: "" });
defineEmits<{ clear: [] }>();
const { t } = useI18n();
const visible = ref(false);
</script>

<template>
  <div class="secret">
    <VTextField v-model="model" :label="label" :type="visible ? 'text' : 'password'" :placeholder="isSet ? t('settings.secretSet') : ''"
      persistent-placeholder :hint="hint" :persistent-hint="!!hint" autocomplete="off"
      :append-inner-icon="visible ? mdiEyeOff : mdiEye" @click:append-inner="visible = !visible" />
    <VBtn v-if="isSet" variant="tonal" color="error" class="clear" :data-test="clearTest" @click="$emit('clear')">
      {{ t("settings.clearSecret") }}
    </VBtn>
  </div>
</template>

<style scoped>
.secret { display: flex; gap: 8px; align-items: flex-start; }
.secret > :first-child { flex: 1; }
.clear { margin-top: 8px; }
</style>

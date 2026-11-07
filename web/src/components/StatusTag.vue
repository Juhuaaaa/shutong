<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ status: string; reason?: string | null; count?: number }>();
const { t, te } = useI18n();
const colors: Record<string, string> = {
  published: "success", planned: "primary", ready: "primary", building: "primary", needs_review: "warning",
  failed: "error", duplicate: "secondary", cancelled: "secondary", missing_metadata: "warning",
};
const label = computed(() => {
  const name = te(`status.${props.status}`) ? t(`status.${props.status}`) : props.status;
  const withReason = props.reason ? `${name} · ${t(`reason.${props.reason}`)}` : name;
  return props.count === undefined ? withReason : `${withReason} ${props.count}`;
});
</script>

<template>
  <VChip size="small" variant="tonal" :color="colors[status] ?? 'secondary'">{{ label }}</VChip>
</template>

<script setup lang="ts">
/** The Shutong logo: an open book with a tick on the right page, on the primary gradient tile. */
withDefaults(defineProps<{ size?: number }>(), { size: 40 });
</script>

<template>
  <div class="brand-mark" :style="{ width: `${size}px`, height: `${size}px`, borderRadius: `${size * 0.3}px` }"
    data-test="brand-mark">
    <svg viewBox="0 0 64 64" :width="size * 0.7" :height="size * 0.7" aria-hidden="true">
      <path d="M6 16Q19 10.5 30.5 17V52Q19 46.5 6 51.5Z" fill="#fff" />
      <path d="M58 16Q45 10.5 33.5 17V52Q45 46.5 58 51.5Z" fill="#fff" />
      <path d="M38.5 33.5L44 39L53 26.5" class="check" />
    </svg>
  </div>
</template>

<style scoped>
.brand-mark {
  flex: none; display: grid; place-items: center;
  background: linear-gradient(135deg, rgb(var(--v-theme-primary)), #B39DFF);
}
.check { fill: none; stroke: rgb(var(--v-theme-primary)); stroke-width: 5; stroke-linecap: round; stroke-linejoin: round; }
</style>

<script setup lang="ts">
import AppNotify from "@/components/AppNotify.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
</script>

<template>
  <VApp>
    <RouterView />
    <ConfirmDialog />
    <AppNotify />
  </VApp>
</template>

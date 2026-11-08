<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import AccountSettings from "@/components/settings/AccountSettings.vue";
import AiSettings from "@/components/settings/AiSettings.vue";
import MetadataSettings from "@/components/settings/MetadataSettings.vue";
import NetworkSettings from "@/components/settings/NetworkSettings.vue";
import ServerSettings from "@/components/settings/ServerSettings.vue";

const TABS = ["ai", "metadata", "network", "servers", "account"] as const;
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
// "bangumi" is what the metadata tab was called before there were other sources: old links still land there.
const asked = computed(() => (String(route.params.tab) === "bangumi" ? "metadata" : String(route.params.tab)));
const tab = computed(() => (TABS.includes(asked.value as (typeof TABS)[number]) ? asked.value : "ai"));
const panes = { ai: AiSettings, metadata: MetadataSettings, network: NetworkSettings, servers: ServerSettings,
  account: AccountSettings };
</script>

<template>
  <div class="st-page">
    <h1 class="st-page-title">{{ t("nav.settings") }}</h1>
    <VCard>
      <VTabs :model-value="tab" color="primary" show-arrows class="tabs"
        @update:model-value="(value) => router.replace({ name: 'settings', params: { tab: String(value) } })">
        <VTab v-for="name in TABS" :key="name" :value="name">{{ t(`settings.tabs.${name}`) }}</VTab>
      </VTabs>
      <VDivider />
      <!-- Each pane stays mounted once opened, so switching tabs keeps what was typed but not saved. -->
      <VWindow :model-value="tab" class="pa-6">
        <VWindowItem v-for="name in TABS" :key="name" :value="name">
          <component :is="panes[name]" />
        </VWindowItem>
      </VWindow>
    </VCard>
  </div>
</template>

<style scoped>
.tabs { padding: 0 12px; }
@media (max-width: 599px) {
  .tabs { padding: 0; }
}
</style>

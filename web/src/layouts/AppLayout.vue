<script setup lang="ts">
import {
  mdiBookshelf, mdiCheckDecagramOutline, mdiClipboardTextClockOutline, mdiCogOutline,
  mdiLogout, mdiMenu, mdiThemeLightDark, mdiViewDashboardOutline, mdiWeatherNight,
  mdiTextBoxSearchOutline, mdiTrayArrowUp, mdiWhiteBalanceSunny,
} from "@mdi/js";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { useDisplay } from "vuetify";
import BrandMark from "@/components/BrandMark.vue";
import DropOverlay from "@/components/DropOverlay.vue";
import JobIndicator from "@/components/JobIndicator.vue";
import OriginalsPrompt from "@/components/OriginalsPrompt.vue";
import UpdateBanner from "@/components/UpdateBanner.vue";
import { useThemeMode } from "@/composables/themeMode";
import { useAuth } from "@/stores/auth";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";

const { t } = useI18n();
const auth = useAuth();
const jobs = useJobs();
const libraries = useLibraries();
const router = useRouter();
const { mdAndUp } = useDisplay();
const theme = useThemeMode();
const drawer = ref(mdAndUp.value);

watch(mdAndUp, (wide) => (drawer.value = wide));
onMounted(() => {
  libraries.refresh().catch(() => {});
  jobs.connect();
});
onUnmounted(() => jobs.disconnect());

interface NavItem { name: string; icon: string; badge?: "needs_review" }
const groups: { key: string; items: NavItem[] }[] = [
  { key: "overview", items: [{ name: "dashboard", icon: mdiViewDashboardOutline }] },
  { key: "organize", items: [
    { name: "upload", icon: mdiTrayArrowUp },
    { name: "review", icon: mdiCheckDecagramOutline, badge: "needs_review" },
    { name: "history", icon: mdiClipboardTextClockOutline },
  ] },
  { key: "config", items: [{ name: "libraries", icon: mdiBookshelf }] },
  { key: "system", items: [{ name: "settings", icon: mdiCogOutline }, { name: "logs", icon: mdiTextBoxSearchOutline }] },
];

function badge(item: NavItem) {
  return item.badge ? libraries.total(item.badge) : 0;
}

const themeIcon = computed(() => ({ system: mdiThemeLightDark, light: mdiWhiteBalanceSunny, dark: mdiWeatherNight })[theme.mode.value]);

async function logout() {
  await auth.logout();
  await router.push("/login");
}
</script>

<template>
  <VNavigationDrawer v-model="drawer" :permanent="mdAndUp" :temporary="!mdAndUp" width="248" border="0"
    class="nav" data-test="nav-drawer">
    <div class="brand">
      <BrandMark />
      <div>
        <div class="brand-name">{{ t("app.name") }}</div>
        <div class="brand-tagline">{{ t("nav.tagline") }}</div>
      </div>
    </div>
    <VList nav density="comfortable" class="px-3" color="primary">
      <template v-for="group in groups" :key="group.key">
        <VListSubheader class="nav-group" data-test="nav-group">{{ t(`nav.groups.${group.key}`) }}</VListSubheader>
        <VListItem v-for="item in group.items.filter((entry) => !(auth.desktop && entry.name === 'upload'))" :key="item.name" :to="{ name: item.name }" :exact="item.name === 'dashboard'" :prepend-icon="item.icon" rounded="lg" :data-test="`nav-${item.name}`"
          @click="!mdAndUp && (drawer = false)">
          <VListItemTitle>{{ t(`nav.${item.name}`) }}</VListItemTitle>
          <template v-if="badge(item)" #append>
            <VChip size="x-small" variant="flat" :color="'warning'"
              :data-test="`badge-${item.name}`">
{{ badge(item) }}
</VChip>
          </template>
        </VListItem>
      </template>
    </VList>
  </VNavigationDrawer>

  <VAppBar flat height="64" class="bar">
    <VAppBarNavIcon v-if="!mdAndUp" :icon="mdiMenu" :aria-label="t('nav.menu')" @click="drawer = !drawer" />
    <VSpacer />
    <JobIndicator />
    <VBtn icon variant="text" :title="t(`nav.theme.${theme.mode.value}`)" data-test="theme-toggle" @click="theme.cycle()">
      <VIcon :icon="themeIcon" />
    </VBtn>
    <VBtn v-if="!auth.desktop" icon variant="text" :title="t('nav.logout')" class="mr-2" data-test="logout" @click="logout"><VIcon :icon="mdiLogout" /></VBtn>
  </VAppBar>

  <DropOverlay v-if="auth.desktop" />
  <VMain class="main">
    <div class="content">
      <template v-if="auth.desktop">
        <UpdateBanner />
        <OriginalsPrompt />
      </template>
      <RouterView />
    </div>
  </VMain>
</template>

<style scoped>
.nav { background: rgb(var(--v-theme-surface)); box-shadow: var(--st-shadow); }
.brand { display: flex; align-items: center; gap: 12px; padding: 20px 20px 12px; }
.brand-name { font-size: 18px; font-weight: 700; }
.brand-tagline { font-size: 12px; opacity: 0.6; }
.nav-group { font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: none; opacity: 0.7; margin-top: 8px; }
.bar { background: rgb(var(--v-theme-background)) !important; }
.main { background: rgb(var(--v-theme-background)); }
.content { padding: 8px 28px 32px; max-width: 1600px; margin: 0 auto; }
@media (max-width: 599px) {
  .content { padding: 4px 16px 24px; }
}
</style>

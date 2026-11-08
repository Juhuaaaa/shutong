<script setup lang="ts">
import { mdiFolderOpenOutline } from "@mdi/js";
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { libraries as api } from "@/api";
import { ApiError } from "@/api/client";
import AiSettings from "@/components/settings/AiSettings.vue";
import MetadataSettings from "@/components/settings/MetadataSettings.vue";
import { bridge } from "@/composables/desktop";
import { useAuth } from "@/stores/auth";
import { useLibraries } from "@/stores/libraries";

const KINDS = ["manga", "novel"] as const;
const { t } = useI18n();
const router = useRouter();
const libraries = useLibraries();
const step = ref(1);
const auth = useAuth();
const dirs = reactive({ manga: "", novel: "" });
/** On a server: the folders as the container sees them, and which libraries are wanted at all. */
const server = reactive({
  manga: { want: true, source: "", library: "" },
  novel: { want: true, source: "", library: "" },
});
const wanted = computed(() => KINDS.filter((kind) => server[kind].want));
const ready = computed(() => (auth.desktop
  ? Boolean(dirs.manga.trim() && dirs.novel.trim())
  : wanted.value.length > 0 && wanted.value.every((kind) => server[kind].source.trim() && server[kind].library.trim())));
const error = ref("");
const saving = ref(false);

onMounted(async () => {
  for (const kind of KINDS) dirs[kind] = (await bridge()?.defaultLibraryDir(kind)) ?? "";
});

const aiForm = ref<InstanceType<typeof AiSettings> | null>(null);
const bangumiForm = ref<InstanceType<typeof MetadataSettings> | null>(null);

/** Going on keeps what was typed; the form's own save button is easy to miss. */
async function saveAndGo(form: { commit(): Promise<boolean> } | null, next: number) {
  if (!form || (await form.commit())) step.value = next;
}

async function pick(kind: (typeof KINDS)[number]) {
  const picked = await bridge()?.pickFolder(dirs[kind] || undefined);
  if (picked) dirs[kind] = picked;
}

async function createLibraries() {
  error.value = "";
  saving.value = true;
  try {
    const existing = await api.list();
    for (const kind of auth.desktop ? KINDS : wanted.value) {
      if (existing.some((library) => library.kind === kind)) continue; // a second try after one of them failed
      const folders = auth.desktop
        ? { source_dir: "", library_dir: dirs[kind] }  // the desktop takes files dropped from anywhere
        : { source_dir: server[kind].source.trim(), library_dir: server[kind].library.trim() };
      await api.create({ name: t(`desktop.welcome.libraries.${kind}`), kind, ...folders, source_policy: "keep" } as never);
    }
    await libraries.refresh();
    step.value = 2;
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.detail : String(reason);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <VMain class="welcome">
    <VCard class="card pa-8">
      <h1 class="text-h5 mb-1">{{ t("desktop.welcome.title") }}</h1>
      <div class="st-muted text-caption mb-6">{{ step }} / 4</div>

      <section v-if="step === 1" data-test="step-libraries">
        <template v-if="auth.desktop">
          <h2 class="text-subtitle-1 font-weight-medium mb-2">{{ t("desktop.welcome.libraries.title") }}</h2>
          <p class="st-muted mb-6">{{ t("desktop.welcome.libraries.text") }}</p>
          <VTextField v-for="kind in KINDS" :key="kind" v-model="dirs[kind]" :label="t(`desktop.welcome.libraries.${kind}`)"
            :append-inner-icon="mdiFolderOpenOutline" :data-test="`dir-${kind}`" @click:append-inner="pick(kind)" />
        </template>
        <template v-else>
          <h2 class="text-subtitle-1 font-weight-medium mb-2">{{ t("desktop.welcome.server.title") }}</h2>
          <p class="st-muted mb-6">{{ t("desktop.welcome.server.text") }}</p>
          <div v-for="kind in KINDS" :key="kind" class="kind">
            <VSwitch v-model="server[kind].want" :label="t(`desktop.welcome.libraries.${kind}`)" hide-details
              :data-test="`want-${kind}`" />
            <template v-if="server[kind].want">
              <VTextField v-model="server[kind].source" :label="t('desktop.welcome.server.source')"
                :placeholder="`/data/downloads/${kind}`" persistent-placeholder :data-test="`source-${kind}`" />
              <VTextField v-model="server[kind].library" :label="t('desktop.welcome.server.library')"
                :placeholder="`/data/library/${kind}`" persistent-placeholder :data-test="`library-${kind}`" />
            </template>
          </div>
        </template>
        <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg" class="mb-4" data-test="error">{{ error }}</VAlert>
        <div class="actions">
          <VBtn color="primary" :loading="saving" :disabled="!ready" data-test="next-libraries"
            @click="createLibraries">{{ t("desktop.welcome.next") }}</VBtn>
        </div>
      </section>

      <section v-else-if="step === 2" data-test="step-ai">
        <h2 class="text-subtitle-1 font-weight-medium mb-2">{{ t("desktop.welcome.ai.title") }}</h2>
        <p class="st-muted mb-4">{{ t("desktop.welcome.ai.text") }}</p>
        <VAlert type="info" variant="tonal" density="compact" rounded="lg" class="mb-6" data-test="privacy">{{ t("desktop.welcome.ai.privacy") }}</VAlert>
        <AiSettings ref="aiForm" />
        <p class="st-muted text-caption mt-4">{{ t("desktop.welcome.ai.laterHint") }}</p>
        <div class="actions">
          <VBtn variant="text" data-test="later-ai" @click="step = 3">{{ t("desktop.welcome.later") }}</VBtn>
          <VBtn color="primary" data-test="next-ai" @click="saveAndGo(aiForm, 3)">{{ t("desktop.welcome.next") }}</VBtn>
        </div>
      </section>

      <section v-else-if="step === 3" data-test="step-bangumi">
        <h2 class="text-subtitle-1 font-weight-medium mb-2">{{ t("desktop.welcome.bangumi.title") }}</h2>
        <p class="st-muted mb-6">{{ t("desktop.welcome.bangumi.text") }}</p>
        <MetadataSettings ref="bangumiForm" />
        <div class="actions">
          <VBtn color="primary" data-test="next-bangumi" @click="saveAndGo(bangumiForm, 4)">{{ t("desktop.welcome.next") }}</VBtn>
        </div>
      </section>

      <section v-else data-test="step-done">
        <h2 class="text-subtitle-1 font-weight-medium mb-2">{{ t("desktop.welcome.done.title") }}</h2>
        <p class="st-muted mb-6">{{ t(auth.desktop ? "desktop.welcome.done.text" : "desktop.welcome.done.server") }}</p>
        <div class="actions">
          <VBtn color="primary" data-test="finish" @click="router.push({ name: 'dashboard' })">{{ t("desktop.welcome.finish") }}</VBtn>
        </div>
      </section>
    </VCard>
  </VMain>
</template>

<style scoped>
.welcome { display: flex; justify-content: center; padding: 32px 16px; }
.card { width: 100%; max-width: 720px; margin: 0 auto; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.kind { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
</style>

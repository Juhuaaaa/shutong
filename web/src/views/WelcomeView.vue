<script setup lang="ts">
import { mdiFolderOpenOutline } from "@mdi/js";
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { libraries as api } from "@/api";
import { ApiError } from "@/api/client";
import AiSettings from "@/components/settings/AiSettings.vue";
import MetadataSettings from "@/components/settings/MetadataSettings.vue";
import { bridge } from "@/composables/desktop";
import { useLibraries } from "@/stores/libraries";

const KINDS = ["manga", "novel"] as const;
const { t } = useI18n();
const router = useRouter();
const libraries = useLibraries();
const step = ref(1);
const dirs = reactive({ manga: "", novel: "" });
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
    for (const kind of KINDS) {
      if (existing.some((library) => library.kind === kind)) continue; // a second try after one of them failed
      await api.create({ name: t(`desktop.welcome.libraries.${kind}`), kind, source_dir: "", library_dir: dirs[kind], source_policy: "keep" } as never);
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
        <h2 class="text-subtitle-1 font-weight-medium mb-2">{{ t("desktop.welcome.libraries.title") }}</h2>
        <p class="st-muted mb-6">{{ t("desktop.welcome.libraries.text") }}</p>
        <VTextField v-for="kind in KINDS" :key="kind" v-model="dirs[kind]" :label="t(`desktop.welcome.libraries.${kind}`)"
          :append-inner-icon="mdiFolderOpenOutline" :data-test="`dir-${kind}`" @click:append-inner="pick(kind)" />
        <VAlert v-if="error" type="error" variant="tonal" density="compact" rounded="lg" class="mb-4" data-test="error">{{ error }}</VAlert>
        <div class="actions">
          <VBtn color="primary" :loading="saving" :disabled="!dirs.manga.trim() || !dirs.novel.trim()" data-test="next-libraries"
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
        <p class="st-muted mb-6">{{ t("desktop.welcome.done.text") }}</p>
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
</style>

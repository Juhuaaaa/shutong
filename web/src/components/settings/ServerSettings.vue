<script setup lang="ts">
import { mdiDeleteOutline, mdiLanConnect, mdiPencilOutline, mdiPlus, mdiServerNetwork } from "@mdi/js";
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { servers as api, type Server } from "@/api";
import type { ApiError } from "@/api/client";
import { ask } from "@/composables/confirm";
import { notify } from "@/composables/notify";
import { MASK } from "@/composables/useSettingsForm";

const { t } = useI18n();
const list = ref<Server[]>([]);
const editing = ref<Server | null | undefined>(undefined);
const form = reactive({ name: "", base_url: "", username: "", password: "" });
const results = ref<Record<number, { ok: boolean; text: string }>>({});

function failed(error: unknown) {
  notify.error((error as ApiError).detail ?? String(error));
}

async function load() {
  list.value = await api.list();
}
onMounted(() => load().catch(failed));

function open(server: Server | null) {
  editing.value = server;
  Object.assign(form, { name: server?.name ?? t("settings.serverDefaultName"), base_url: server?.base_url ?? "http://",
    username: server?.username ?? "", password: "" });
}

async function save() {
  try {
    if (editing.value) {
      await api.update(editing.value.id, { name: form.name, base_url: form.base_url, username: form.username,
        password: form.password || MASK });
    } else {
      await api.create({ kind: "kavita", ...form });
    }
    editing.value = undefined;
    await load();
  } catch (error) {
    failed(error);
  }
}

async function test(server: Server) {
  try {
    const result = await api.test(server.id);
    results.value = { ...results.value, [server.id]: result.ok
      ? { ok: true, text: t("settings.serverOk", { libraries: result.libraries.map((entry) => `${entry.name}(${entry.id})`).join("、") }) }
      : { ok: false, text: result.error ?? "" } };
  } catch (error) {
    failed(error);
  }
}

async function remove(server: Server) {
  if (!(await ask(t("settings.serverRemoveTitle"), t("settings.serverRemoveText", { name: server.name }), true))) return;
  try {
    await api.remove(server.id);
    await load();
  } catch (error) {
    failed(error);
  }
}
</script>

<template>
  <div class="d-flex mb-4">
    <VSpacer />
    <VBtn color="primary" :prepend-icon="mdiPlus" @click="open(null)">{{ t("settings.serverAdd") }}</VBtn>
  </div>
  <div class="servers">
    <VCard v-for="server in list" :key="server.id" class="pa-4 st-flat server" variant="outlined">
      <div class="d-flex align-center ga-3">
        <VAvatar color="primary" variant="tonal" rounded="lg"><VIcon :icon="mdiServerNetwork" /></VAvatar>
        <div class="min-w-0">
          <div class="font-weight-bold">{{ server.name }}</div>
          <div class="st-muted text-caption">{{ server.kind }} · {{ server.base_url }} · {{ server.username }}</div>
        </div>
        <VSpacer />
        <VChip v-if="!server.enabled" size="small">{{ t("settings.disabled") }}</VChip>
      </div>
      <VAlert v-if="results[server.id]" :type="results[server.id].ok ? 'success' : 'error'" variant="tonal" density="compact"
        rounded="lg" class="mt-3">
{{ results[server.id].text }}
</VAlert>
      <div class="d-flex ga-2 mt-3 flex-wrap">
        <VBtn size="small" variant="tonal" :prepend-icon="mdiLanConnect" @click="test(server)">{{ t("settings.testConnection") }}</VBtn>
        <VBtn size="small" variant="text" :prepend-icon="mdiPencilOutline" @click="open(server)">{{ t("common.edit") }}</VBtn>
        <VBtn size="small" variant="text" color="error" :prepend-icon="mdiDeleteOutline" @click="remove(server)">{{ t("common.remove") }}</VBtn>
      </div>
    </VCard>
  </div>
  <VDialog :model-value="editing !== undefined" max-width="480" @update:model-value="(open) => !open && (editing = undefined)">
    <VCard class="pa-2">
      <VCardTitle>{{ editing ? editing.name : t("settings.serverAdd") }}</VCardTitle>
      <VCardText class="d-flex flex-column ga-1">
        <VTextField v-model="form.name" :label="t('library.name')" />
        <VTextField v-model="form.base_url" :label="t('settings.serverUrl')" placeholder="http://192.168.1.10:5000" />
        <VTextField v-model="form.username" :label="t('settings.serverUser')" />
        <VTextField v-model="form.password" :label="t('settings.serverPassword')" type="password" autocomplete="off"
          :placeholder="editing?.password ? MASK : ''" persistent-placeholder />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="editing = undefined">{{ t("common.cancel") }}</VBtn>
        <VBtn color="primary" variant="flat" @click="save">{{ t("common.save") }}</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.servers { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
.server { border-color: rgba(var(--v-border-color), var(--v-border-opacity)); }
.min-w-0 { min-width: 0; word-break: break-all; }
@media (max-width: 599px) {
  .servers { grid-template-columns: minmax(0, 1fr); }
}
</style>

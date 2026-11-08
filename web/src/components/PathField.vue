<script setup lang="ts">
/**
 * A folder on the server, typed or picked from a tree that opens beneath the field (a server's page has no folder
 * dialog). The tree opens along the path already typed; clicking a folder fills it in and shows what is inside.
 */
import { mdiFolder, mdiFolderOpen } from "@mdi/js";
import { computed, reactive, ref } from "vue";
import { folders as api } from "@/api";

defineOptions({ inheritAttrs: false });  // data-test and the like belong on the field, not on the menu
const model = defineModel<string>({ default: "" });
defineProps<{ label?: string; placeholder?: string; hint?: string; errorMessages?: string }>();

interface Node { path: string; name: string; open: boolean; children: string[] | null; failed: boolean }

const ROOT = "/";
const nodes = reactive(new Map<string, Node>());
const menu = ref(false);

function join(parent: string, name: string): string {
  return parent === ROOT ? `/${name}` : `${parent}/${name}`;
}

function node(path: string, name: string): Node {
  if (!nodes.has(path)) nodes.set(path, { path, name, open: false, children: null, failed: false });
  return nodes.get(path)!;
}

async function load(entry: Node) {
  if (entry.children !== null) return;
  try {
    entry.children = (await api.list(entry.path)).folders.map((name) => join(entry.path, name));
    for (const child of entry.children) node(child, child.slice(child.lastIndexOf("/") + 1));
  } catch {
    entry.children = [];
    entry.failed = true;  // unreadable or gone: shown, but nothing beneath
  }
}

/** Open the tree from the top down to the folder typed, as far as it exists. */
async function reveal() {
  const root = node(ROOT, ROOT);
  root.open = true;
  await load(root);
  let current = ROOT;
  for (const part of model.value.split("/").filter(Boolean)) {
    const next = join(current, part);
    if (!nodes.has(next)) break;
    const entry = nodes.get(next)!;
    entry.open = true;
    await load(entry);
    current = next;
  }
}

async function pick(entry: Node) {
  model.value = entry.path;
  entry.open = !entry.open || entry.children === null;
  if (entry.open) await load(entry);
}

/** The open part of the tree, top to bottom, with each folder's depth for indenting. */
const rows = computed(() => {
  const shown: { entry: Node; depth: number }[] = [];
  const walk = (path: string, depth: number) => {
    const entry = nodes.get(path);
    if (!entry) return;
    shown.push({ entry, depth });
    if (entry.open) for (const child of entry.children ?? []) walk(child, depth + 1);
  };
  walk(ROOT, 0);
  return shown;
});

function opened(open: boolean) {
  menu.value = open;
  if (open) void reveal();
}
</script>

<template>
  <VMenu :model-value="menu" :close-on-content-click="false" location="bottom start" max-height="360" :open-on-click="false"
    @update:model-value="opened">
    <template #activator="{ props: activator }">
      <VTextField v-bind="{ ...activator, ...$attrs }" v-model="model" :label="label" :placeholder="placeholder" persistent-placeholder
        :hint="hint" :persistent-hint="!!hint" :error-messages="errorMessages" autocomplete="off" @focus="opened(true)" />
    </template>
    <VCard class="tree" data-test="folder-tree">
      <div v-for="{ entry, depth } in rows" :key="entry.path" class="row" :class="{ current: entry.path === model }"
        :style="{ paddingLeft: `${12 + depth * 20}px` }" role="button" tabindex="0" data-test="folder-row"
        @click="pick(entry)" @keydown.enter="pick(entry)">
        <VIcon :icon="entry.open ? mdiFolderOpen : mdiFolder" size="20" color="primary" />
        <span :class="{ 'st-muted': entry.failed }">{{ entry.name }}</span>
      </div>
    </VCard>
  </VMenu>
</template>

<style scoped>
.tree { min-width: 280px; padding: 6px 0; overflow-y: auto; }
.row { display: flex; align-items: center; gap: 10px; padding-top: 7px; padding-bottom: 7px; padding-right: 16px; cursor: pointer; }
.row:hover, .row:focus-visible { background: rgba(var(--v-theme-primary), 0.08); outline: none; }
.row.current { background: rgba(var(--v-theme-primary), 0.14); }
</style>

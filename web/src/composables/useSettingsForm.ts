/** Settings form state: load once, edit locally, PATCH only the keys that changed. */
import { computed, reactive, ref, type WritableComputedRef } from "vue";
import { settings as api, type Settings } from "@/api";

export const MASK = "已设置";

export function useSettingsForm(keys: string[]) {
  const values = reactive<Record<string, unknown>>({});
  const initial = ref<Settings>({});
  const secretSet = reactive<Record<string, boolean>>({});

  async function load() {
    const loaded = await api.get();
    initial.value = loaded;
    for (const key of keys) {
      secretSet[key] = loaded[key] === MASK; // false again once a secret was cleared
      if (secretSet[key]) {
        values[key] = ""; // empty box with a "已设置" placeholder; typing replaces the secret
      } else {
        values[key] = loaded[key];
      }
    }
  }

  function changes(): Settings {
    const changed: Settings = {};
    for (const key of keys) {
      const value = values[key];
      if (secretSet[key]) {
        if (value !== "") changed[key] = value;
      } else if (!same(value, initial.value[key]) && !(value === null && initial.value[key] === "")) {
        changed[key] = value;
      }
    }
    return changed;
  }

  async function save(): Promise<number> {
    const changed = changes();
    if (Object.keys(changed).length) await apply(changed);
    return Object.keys(changed).length;
  }

  async function apply(changed: Settings) {
    await api.update(changed);
    await load();
  }

  /** A v-model for one key (templates cannot bind ``values[key] as T`` two-way). */
  function field<T>(key: string): WritableComputedRef<T> {
    return computed({ get: () => values[key] as T, set: (value: T) => (values[key] = value) });
  }

  return { values, secretSet, load, changes, save, apply, field };
}

/** Lists (the metadata source order) compare by content, not by identity. */
function same(a: unknown, b: unknown): boolean {
  return Array.isArray(a) || Array.isArray(b) ? JSON.stringify(a) === JSON.stringify(b) : a === b;
}

import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { libraries as api, type Library } from "@/api";
import { useJobs } from "./jobs";

const CURRENT_KEY = "shutong.library";

function stored(): number | null {
  try {
    const value = localStorage.getItem(CURRENT_KEY);
    return value ? Number(value) : null;
  } catch {
    return null;
  }
}

export const useLibraries = defineStore("libraries", () => {
  const list = ref<Library[]>([]);
  const summaries = ref<Record<number, Record<string, number>>>({});
  const currentId = ref<number | null>(stored());
  const loaded = ref(false);

  const current = computed(() => list.value.find((library) => library.id === currentId.value) ?? list.value[0] ?? null);

  async function refresh() {
    list.value = await api.list();
    loaded.value = true;
    const entries = await Promise.all(list.value.map(async (library) => [library.id, (await api.summary(library.id)).counts]));
    summaries.value = Object.fromEntries(entries);
  }

  function select(id: number) {
    currentId.value = id;
    try {
      localStorage.setItem(CURRENT_KEY, String(id));
    } catch {
      /* private mode: the choice just isn't remembered */
    }
  }

  function count(id: number | undefined, status: string): number {
    return id === undefined ? 0 : (summaries.value[id]?.[status] ?? 0);
  }

  function total(status: string): number {
    return list.value.reduce((sum, library) => sum + count(library.id, status), 0);
  }

  function kindOf(id: number): "manga" | "novel" {
    return (list.value.find((library) => library.id === id)?.kind ?? "manga") as "manga" | "novel";
  }

  useJobs().onFinished(["scan", "execute", "confirm", "reorganize", "retry", "reidentify", "metadata"], () => {
    refresh().catch(() => {});
  });

  return { list, summaries, current, loaded, refresh, select, count, total, kindOf };
});

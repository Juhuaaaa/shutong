import { computed, ref } from "vue";

/** A set of selected ids with helpers for selecting a whole group at once. */
export function useSelection() {
  const selected = ref<Set<number>>(new Set());
  const count = computed(() => selected.value.size);

  function set(ids: Iterable<number>) {
    selected.value = new Set(ids);
  }
  function has(id: number) {
    return selected.value.has(id);
  }
  function toggle(id: number, on = !selected.value.has(id)) {
    const next = new Set(selected.value);
    if (on) next.add(id);
    else next.delete(id);
    selected.value = next;
  }
  function state(ids: number[]): "all" | "some" | "none" {
    const hits = ids.filter((id) => selected.value.has(id)).length;
    return hits === 0 ? "none" : hits === ids.length ? "all" : "some";
  }
  function toggleGroup(ids: number[]) {
    const next = new Set(selected.value);
    const on = state(ids) !== "all";
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    selected.value = next;
  }
  return { selected, count, set, has, toggle, state, toggleGroup };
}

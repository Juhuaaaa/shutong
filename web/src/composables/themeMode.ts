/** Light / dark / follow the system, remembered per browser. */
import { ref } from "vue";
import { useTheme } from "vuetify";

export type ThemeMode = "system" | "light" | "dark";
const KEY = "shutong.theme";
const ORDER: ThemeMode[] = ["system", "light", "dark"];

export function storedThemeMode(): ThemeMode {
  try {
    const value = localStorage.getItem(KEY);
    return ORDER.includes(value as ThemeMode) ? (value as ThemeMode) : "system";
  } catch {
    return "system";
  }
}

const mode = ref<ThemeMode>(storedThemeMode());

export function useThemeMode() {
  const theme = useTheme();
  function set(next: ThemeMode) {
    mode.value = next;
    theme.change(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* private mode: not remembered */
    }
  }
  return { mode, set, cycle: () => set(ORDER[(ORDER.indexOf(mode.value) + 1) % ORDER.length]) };
}

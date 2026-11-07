/** Vuetify with the Shutong look: purple primary, flat soft cards, follows the system light/dark. */
import { createVuetify, type ThemeDefinition } from "vuetify";
import { aliases, mdi } from "vuetify/iconsets/mdi-svg";
import { en, zhHans } from "vuetify/locale";
import { i18n } from "@/i18n";

const light: ThemeDefinition = {
  dark: false,
  colors: {
    primary: "#7C4DFF",
    secondary: "#8A8D9F",
    background: "#F4F5FA",
    surface: "#FFFFFF",
    "surface-variant": "#EEF0F6",
    success: "#28C76F",
    warning: "#FF9F43",
    error: "#EA5455",
    info: "#00BAD1",
  },
};

const dark: ThemeDefinition = {
  dark: true,
  colors: {
    primary: "#9575FF",
    secondary: "#9DA0B4",
    background: "#16171D",
    surface: "#1F2029",
    "surface-variant": "#2A2C37",
    success: "#28C76F",
    warning: "#FF9F43",
    error: "#EA5455",
    info: "#00BAD1",
  },
};

export function createAppVuetify(defaultTheme: "light" | "dark" | "system" = "system") {
  return createVuetify({
    theme: { defaultTheme, themes: { light, dark } },
    icons: { defaultSet: "mdi", aliases, sets: { mdi } },
    locale: { locale: i18n.global.locale.value === "en" ? "en" : "zhHans", fallback: "zhHans", messages: { zhHans, en } },
    defaults: {
      VCard: { elevation: 0, rounded: "xl" },
      VBtn: { rounded: "lg", elevation: 0 },
      VTextField: { variant: "outlined", density: "comfortable", rounded: "lg", color: "primary" },
      VTextarea: { variant: "outlined", density: "comfortable", rounded: "lg", color: "primary" },
      VSelect: { variant: "outlined", density: "comfortable", rounded: "lg", color: "primary" },
      VCombobox: { variant: "outlined", density: "comfortable", rounded: "lg", color: "primary" },
      VSwitch: { color: "primary", inset: true, hideDetails: "auto" },
      VCheckbox: { color: "primary", hideDetails: true },
      VCheckboxBtn: { color: "primary" },
      VChip: { rounded: "lg" },
      VDialog: { maxWidth: 560 },
    },
  });
}

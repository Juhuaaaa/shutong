import { createI18n } from "vue-i18n";
import en from "./locales/en";
import zhCN from "./locales/zh-CN";

export const LOCALES = [{ value: "zh-CN", title: "简体中文" }, { value: "en", title: "English" }] as const;
export type Locale = (typeof LOCALES)[number]["value"];

const STORAGE_KEY = "shutong.locale";

/** What the person chose, else the browser's language: Chinese browsers get Chinese, all others English. */
function saved(): Locale {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "en" || value === "zh-CN") return value;
  } catch {
    // Storage refused: fall through to the browser's language.
  }
  return typeof navigator !== "undefined" && navigator.language && !navigator.language.toLowerCase().startsWith("zh") ? "en" : "zh-CN";
}

export const i18n = createI18n({ legacy: false, locale: saved(), fallbackLocale: "zh-CN", messages: { "zh-CN": zhCN, en } });
export const t = i18n.global.t;

function apply(locale: Locale) {
  if (typeof document !== "undefined") document.documentElement.lang = locale;
}

apply(saved());

export function setLocale(locale: Locale) {
  i18n.global.locale.value = locale;
  apply(locale);
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Private windows may refuse: the choice still holds until the page is closed.
  }
}

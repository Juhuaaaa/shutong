import { afterEach, describe, expect, it } from "vitest";
import { i18n, setLocale, t } from "./i18n";
import en from "./locales/en";
import zhCN from "./locales/zh-CN";

function keys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, entry]) => (
    typeof entry === "object" && entry !== null ? keys(entry, `${prefix}${key}.`) : [`${prefix}${key}`]));
}

function placeholders(text: string) {
  return [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
}

function leaf(source: object, path: string): string {
  return path.split(".").reduce((node: unknown, part) => (node as Record<string, unknown>)[part], source) as string;
}

describe("translations", () => {
  afterEach(() => setLocale("zh-CN"));

  it("English has every key Chinese has, and no other", () => {
    expect(keys(en).sort()).toEqual(keys(zhCN).sort());
  });

  it("every English text takes the same values as its Chinese one", () => {
    for (const key of keys(zhCN)) expect(placeholders(leaf(en, key)), key).toEqual(placeholders(leaf(zhCN, key)));
  });

  it("no Chinese is left in the English texts, except the sample chapter forms it never needs", () => {
    const left = keys(en).filter((key) => /[一-鿿]/.test(leaf(en, key)));
    expect(left).toEqual([]);
  });

  it("switching takes effect and is remembered", () => {
    setLocale("en");
    expect(t("nav.review")).toBe("Review");
    expect(localStorage.getItem("shutong.locale")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    setLocale("zh-CN");
    expect(t("nav.review")).toBe("复核");
  });

  it("starts in the chosen language", () => {
    expect(i18n.global.locale.value).toBe("zh-CN");
  });
});

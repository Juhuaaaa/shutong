import { afterEach, describe, expect, it, vi } from "vitest";
import { mountWith } from "@/test-mount";
import { fakeApi, flush } from "@/test-utils";
import PathField from "./PathField.vue";

const TREE: Record<string, string[]> = { "/": ["app", "data"], "/data": ["下载", "书库"], "/data/下载": ["漫画"], "/data/下载/漫画": [] };

function serve() {
  return fakeApi({
    "GET /api/folders": (_body: unknown, url: URL) => {
      const path = url.searchParams.get("path") ?? "/";
      const parent = path === "/" ? null : path.slice(0, path.lastIndexOf("/")) || "/";
      return { path, parent, folders: TREE[path] ?? [] };
    },
  });
}

function rows() {
  return [...document.querySelectorAll("[data-test=folder-row]")].map((row) => row.textContent?.trim());
}

describe("PathField", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("opens the folder tree along the path typed, and picks a folder by clicking it", async () => {
    serve();
    const wrapper = mountWith(PathField, { modelValue: "/data/下载", label: "来源目录" });
    await wrapper.find("input").trigger("focus");
    await vi.waitFor(() => expect(rows()).toEqual(["/", "app", "data", "下载", "漫画", "书库"]));
    const 漫画 = [...document.querySelectorAll("[data-test=folder-row]")].find((row) => row.textContent?.trim() === "漫画") as HTMLElement;
    漫画.click();
    await flush();
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["/data/下载/漫画"]);
  });

  it("starts at the top when nothing is typed, and a folder clicked opens beneath", async () => {
    serve();
    const wrapper = mountWith(PathField, { modelValue: "", label: "书库目录" });
    await wrapper.find("input").trigger("focus");
    await vi.waitFor(() => expect(rows()).toEqual(["/", "app", "data"]));
    ([...document.querySelectorAll("[data-test=folder-row]")].find((row) => row.textContent?.trim() === "data") as HTMLElement).click();
    await vi.waitFor(() => expect(rows()).toEqual(["/", "app", "data", "下载", "书库"]));
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["/data"]);
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { mountWith } from "@/test-mount";
import UpdateBanner from "./UpdateBanner.vue";

describe("UpdateBanner", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the new version and opens the download page outside the window", async () => {
    const openExternal = vi.fn();
    let announce: (info: { version: string; url: string }) => void = () => {};
    vi.stubGlobal("shutong", { openExternal, onUpdate: (callback: typeof announce) => (announce = callback) });
    const wrapper = mountWith(UpdateBanner);
    expect(wrapper.find("[data-test=update-banner]").exists()).toBe(false);
    announce({ version: "0.2.0", url: "https://example.test/release" });
    await nextTick();
    expect(wrapper.find("[data-test=update-banner]").text()).toContain("0.2.0");
    await wrapper.find("[data-test=update-download]").trigger("click");
    expect(openExternal).toHaveBeenCalledWith("https://example.test/release");
  });
});

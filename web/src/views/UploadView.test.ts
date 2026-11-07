import { afterEach, describe, expect, it, vi } from "vitest";
import { mountView } from "@/test-mount";
import { fakeApi } from "@/test-utils";
import UploadView from "./UploadView.vue";

const library = (id: number, name: string) => ({
  id, name, kind: "manga", source_dir: `/s${id}`, library_dir: `/l${id}`, naming_template: "", source_policy: "keep",
  archive_dir: null, pdf_to_cbz: true, include_edition: true, overwrite_policy: "never", rename_files: true, available: true, server_id: null, server_library_id: null,
});

describe("UploadView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uploads into the chosen library and organizes it", async () => {
    const { calls } = fakeApi({
      "GET /api/libraries": [library(1, "漫画"), library(2, "轻小说")],
      "GET /api/libraries/1/summary": { counts: {} }, "GET /api/libraries/2/summary": { counts: {} },
      "POST /api/libraries/2/upload": { saved: [{ name: "Vol.01.zip", path: "迷宫饭/Vol.01.zip" }], skipped: [] },
      "POST /api/libraries/2/scan": { job_id: 4 },
      "GET /api/jobs/4": { id: 4, kind: "scan", state: "done", result: { counts: { executed: 1, needs_review: 1 } } },
    });
    const { wrapper } = await mountView(UploadView, "/upload");
    await vi.waitFor(() => expect(wrapper.findAll("[data-test=target]").length).toBe(2));
    await wrapper.findAll("[data-test=target]")[1].trigger("click");
    const input = wrapper.find("[data-test=file-input]");
    const file = new File(["x"], "Vol.01.zip");
    Object.defineProperty(input.element, "files", { value: [file] });
    await input.trigger("change");
    await vi.waitFor(() => expect(wrapper.find("[data-test=result]").exists()).toBe(true));
    const paths = calls.map((call) => `${call.method} ${call.path}`);
    expect(paths).toContain("POST /api/libraries/2/upload");
    expect(paths).toContain("POST /api/libraries/2/scan");
    expect(paths).not.toContain("POST /api/libraries/1/upload");
    expect(wrapper.find("[data-test=result]").text()).toContain("入库 1");
    expect(wrapper.find("[data-test=result]").text()).toContain("去复核");
  });
});

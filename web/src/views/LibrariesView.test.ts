import { afterEach, describe, expect, it, vi } from "vitest";
import { notifyState } from "@/composables/notify";
import { mountView } from "@/test-mount";
import { fakeApi } from "@/test-utils";
import LibrariesView from "./LibrariesView.vue";

const library = {
  id: 1, name: "漫画", kind: "manga", source_dir: "/s", library_dir: "/l", naming_template: "", source_policy: "keep",
  archive_dir: null, pdf_to_cbz: true, overwrite_policy: "never", rename_files: true, available: true, server_id: null, server_library_id: null,
};

describe("LibrariesView", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("tells the scan result", async () => {
    notifyState.queue.splice(0);
    fakeApi({
      "GET /api/libraries": [library], "GET /api/libraries/1/summary": { counts: {} }, "GET /api/servers": [],
      "GET /api/libraries/1/runs": [],
      "POST /api/libraries/1/scan": { job_id: 3 },
      "GET /api/jobs/3": { id: 3, kind: "scan", state: "done", result: { counts: { executed: 5, needs_review: 1 } } },
    });
    const { wrapper } = await mountView(LibrariesView, "/libraries");
    await vi.waitFor(() => expect(wrapper.find("[data-test=scan]").exists()).toBe(true));
    await wrapper.find("[data-test=scan]").trigger("click");
    await vi.waitFor(() => expect(notifyState.queue.map((entry) => entry.text).join()).toContain("入库 5"));
  });
});

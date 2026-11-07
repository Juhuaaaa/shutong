import { afterEach, describe, expect, it, vi } from "vitest";
import { mountWith } from "@/test-mount";
import { FakeSocket, flush } from "@/test-utils";
import * as api from "@/api";
import { useJobs } from "@/stores/jobs";
import { useLibraries } from "@/stores/libraries";
import JobIndicator from "./JobIndicator.vue";

function job(extra: object = {}) {
  return { id: 3, kind: "scan", library_id: 1, state: "running", result: {}, error: null, progress: null,
    created_at: "t", finished_at: null, ...extra };
}

async function indicator() {
  FakeSocket.instances = [];
  const wrapper = mountWith(JobIndicator);
  useLibraries().list = [{ id: 1, name: "漫画" } as never];
  useJobs().connect(FakeSocket as never);
  FakeSocket.instances[0].readyState = 1;
  return wrapper;
}

describe("JobIndicator", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows how many files a scan has settled out of all it found", async () => {
    const wrapper = await indicator();
    FakeSocket.instances[0].push({ type: "job", job: job({ progress: { done: 3618, total: 6869, current: "死神" } }) });
    await flush();
    const chip = wrapper.find("[data-test=job-indicator]");
    expect(chip.text()).toContain("扫描「漫画」");
    expect(chip.text()).toContain("3618 / 6869");
    expect(wrapper.find("[data-test=job-progress]").attributes("aria-valuenow")).toBe("52");
  });

  it("asks the running job to stop", async () => {
    const cancel = vi.spyOn(api.jobs, "cancel").mockResolvedValue(job({ cancelling: true }) as never);
    const wrapper = await indicator();
    FakeSocket.instances[0].push({ type: "job", job: job() });
    await flush();
    await wrapper.find("[data-test=job-stop]").trigger("click");
    expect(cancel).toHaveBeenCalledWith(3);
  });

  it("says a job is stopping and offers no second stop", async () => {
    const wrapper = await indicator();
    FakeSocket.instances[0].push({ type: "job", job: job({ cancelling: true }) });
    await flush();
    expect(wrapper.find("[data-test=job-indicator]").text()).toContain("正在停止");
    expect(wrapper.find("[data-test=job-stop]").exists()).toBe(false);
  });

  it("names the folder being organized", async () => {
    const wrapper = await indicator();
    FakeSocket.instances[0].push({ type: "job", job: job({ progress: { done: 1, total: 2, current: "死神" } }) });
    await flush();
    await wrapper.find("[data-test=job-indicator]").trigger("mouseenter");
    await vi.waitFor(() => expect(document.body.textContent).toContain("正在整理：死神"));
  });

  it("spins without numbers until a job reports progress", async () => {
    const wrapper = await indicator();
    FakeSocket.instances[0].push({ type: "job", job: job() });
    await flush();
    expect(wrapper.find("[data-test=job-indicator]").text()).not.toContain("/");
    expect(wrapper.find("[data-test=job-progress]").exists()).toBe(false);
  });
});

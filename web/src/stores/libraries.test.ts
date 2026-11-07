import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeSocket, fakeApi, flush } from "@/test-utils";
import { useJobs } from "./jobs";
import { useLibraries } from "./libraries";

describe("libraries store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    FakeSocket.instances = [];
  });
  afterEach(() => vi.unstubAllGlobals());

  it("refreshes the counts when an execute job finishes", async () => {
    let planned = 2;
    const { calls } = fakeApi({
      "GET /api/libraries": [{ id: 1, name: "漫画" }],
      "GET /api/libraries/1/summary": () => ({ counts: { planned } }),
      "GET /api/jobs/5": { id: 5, kind: "execute", state: "running", result: {} },
    });
    const libraries = useLibraries();
    await libraries.refresh();
    expect(libraries.count(1, "planned")).toBe(2);
    const jobs = useJobs();
    jobs.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    jobs.submit(Promise.resolve({ job_id: 5 }), "执行");
    await flush();
    planned = 0;
    FakeSocket.instances[0].push({ type: "job", job: { id: 5, kind: "execute", state: "done", result: {} } });
    await vi.waitFor(() => expect(libraries.count(1, "planned")).toBe(0));
    expect(calls.filter((call) => call.path === "/api/libraries").length).toBe(2);
  });

  it("remembers the chosen library", async () => {
    fakeApi({ "GET /api/libraries": [{ id: 1, name: "漫画" }, { id: 2, name: "轻小说" }], "GET /api/libraries/1/summary": { counts: {} },
      "GET /api/libraries/2/summary": { counts: {} } });
    const libraries = useLibraries();
    await libraries.refresh();
    expect(libraries.current?.id).toBe(1);
    libraries.select(2);
    expect(libraries.current?.id).toBe(2);
    expect(localStorage.getItem("shutong.library")).toBe("2");
  });
});

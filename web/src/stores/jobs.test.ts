import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setUnauthorizedHandler } from "@/api/client";
import { FakeSocket, fakeApi, flush } from "@/test-utils";
import { useJobs } from "./jobs";

function job(id: number, state: string, extra: object = {}) {
  return { id, kind: "execute", library_id: null, state, result: {}, error: null, created_at: "t", finished_at: null, ...extra };
}

describe("jobs store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    FakeSocket.instances = [];
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("resolves when the socket reports done", async () => {
    fakeApi({ "GET /api/jobs/7": job(7, "running") });
    const store = useJobs();
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    const finished = store.submit(Promise.resolve({ job_id: 7 }), "执行");
    await flush();
    expect(store.running.map((entry) => entry.id)).toEqual([7]);
    FakeSocket.instances[0].push({ type: "job", job: job(7, "done", { result: { published: 2 } }) });
    expect((await finished).result).toEqual({ published: 2 });
    expect(store.running).toEqual([]);
  });

  it("rejects with the job error when it fails", async () => {
    fakeApi({ "GET /api/jobs/8": job(8, "running") });
    const store = useJobs();
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    const finished = store.submit(Promise.resolve({ job_id: 8 }), "扫描");
    await flush();
    FakeSocket.instances[0].push({ type: "job", job: job(8, "failed", { error: "库目录不可用：x" }) });
    await expect(finished).rejects.toEqual(new ApiError(0, "库目录不可用：x"));
  });

  it("notifies listeners by kind", async () => {
    fakeApi({ "GET /api/jobs/9": job(9, "running") });
    const store = useJobs();
    const listener = vi.fn();
    store.onFinished(["execute", "scan"], listener);
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    store.submit(Promise.resolve({ job_id: 9 }), "执行");
    await flush();
    FakeSocket.instances[0].push({ type: "job", job: job(9, "done") });
    expect(listener).toHaveBeenCalledOnce();
  });

  it("falls back to polling without a socket", async () => {
    vi.useFakeTimers();
    let state = "running";
    fakeApi({ "GET /api/jobs/3": () => job(3, state) });
    const store = useJobs();
    const finished = store.submit(Promise.resolve({ job_id: 3 }), "扫描");
    await vi.advanceTimersByTimeAsync(10);
    state = "done";
    await vi.advanceTimersByTimeAsync(2100);
    expect((await finished).state).toBe("done");
  });

  it("resolves a job that finished before submit saw its id", async () => {
    fakeApi({ "GET /api/jobs/12": job(12, "done") });
    const store = useJobs();
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    FakeSocket.instances[0].push({ type: "job", job: job(12, "queued") });
    FakeSocket.instances[0].push({ type: "job", job: job(12, "done", { result: { replanned: 0 } }) });
    const finished = await store.submit(Promise.resolve({ job_id: 12 }), "确认");
    expect(finished.result).toEqual({ replanned: 0 });
  });

  it("checks waiting jobs again after reconnecting", async () => {
    vi.useFakeTimers();
    let state = "running";
    fakeApi({ "GET /api/jobs/13": () => job(13, state) });
    const store = useJobs();
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    let done = false;
    store.submit(Promise.resolve({ job_id: 13 }), "执行").then(() => (done = true));
    await vi.advanceTimersByTimeAsync(10);
    FakeSocket.instances[0].drop(1006);
    await vi.advanceTimersByTimeAsync(2100); // one poll while the socket is down: still running
    state = "done"; // finishes after that poll and before the reconnect; no message will ever arrive
    await vi.advanceTimersByTimeAsync(1000);
    FakeSocket.instances[1].open();
    await vi.advanceTimersByTimeAsync(5000);
    expect(done).toBe(true);
  });

  it("gives up on a job the server no longer knows", async () => {
    vi.useFakeTimers();
    let lost = false;
    fakeApi({ "GET /api/jobs/14": () => (lost ? new Response(JSON.stringify({ detail: "任务不存在" }), { status: 404 }) : job(14, "running")) });
    const store = useJobs();
    const finished = store.submit(Promise.resolve({ job_id: 14 }), "扫描");
    const outcome = finished.catch((error) => error);
    await vi.advanceTimersByTimeAsync(10);
    lost = true;
    await vi.advanceTimersByTimeAsync(2100);
    expect(((await outcome) as ApiError).detail).toBe("任务已丢失（服务可能重启过），请刷新后查看结果");
  });

  it("a stopped job is finished: waiters hear it stopped, listeners refresh", async () => {
    fakeApi({ "GET /api/jobs/21": job(21, "running") });
    const jobs = useJobs();
    jobs.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    const heard: number[] = [];
    jobs.onFinished(["execute"], (finished) => heard.push(finished.id));
    const waiting = jobs.submit(Promise.resolve({ job_id: 21 }), "扫描");
    await flush();
    FakeSocket.instances[0].push({ type: "job", job: job(21, "cancelled") });
    await expect(waiting).rejects.toThrow("已停止");
    expect(heard).toEqual([21]);
    expect(jobs.running).toEqual([]);
  });

  it("tells listeners about failed jobs too", async () => {
    fakeApi({ "GET /api/jobs/15": job(15, "running") });
    const store = useJobs();
    const listener = vi.fn();
    store.onFinished(["execute"], listener);
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].open();
    store.submit(Promise.resolve({ job_id: 15 }), "执行").catch(() => {});
    await flush();
    FakeSocket.instances[0].push({ type: "job", job: job(15, "failed", { error: "库目录不可用：x" }) });
    expect(listener).toHaveBeenCalledOnce();
  });

  it("treats close code 4401 as logged out", () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const store = useJobs();
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].drop(4401);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("reconnects after an ordinary drop", async () => {
    vi.useFakeTimers();
    const store = useJobs();
    store.connect(FakeSocket as never);
    FakeSocket.instances[0].drop(1006);
    await vi.advanceTimersByTimeAsync(3100);
    expect(FakeSocket.instances.length).toBe(2);
  });
});

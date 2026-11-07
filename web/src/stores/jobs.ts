/** Background jobs: submit → wait on /api/ws (or poll) → resolve; listeners refresh pages when kinds finish. */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { jobs as api, type Job, type JobRef } from "@/api";
import { ApiError, notifyUnauthorized } from "@/api/client";
import { t } from "@/i18n";

type SocketFactory = new (url: string) => WebSocket;
type Listener = (job: Job) => void;
interface Waiter {
  resolve: (job: Job) => void;
  reject: (error: Error) => void;
}

const RECONNECT_MS = 3000;
const POLL_MS = 2000;

export const useJobs = defineStore("jobs", () => {
  const known = ref<Record<number, Job & { label?: string }>>({});
  const labels: Record<number, string> = {};
  const waiters = new Map<number, Waiter>();
  const listeners: { kinds: string[]; callback: Listener }[] = [];
  let socket: WebSocket | null = null;
  let factory: SocketFactory | null = null;
  let polling: ReturnType<typeof setInterval> | null = null;

  const running = computed(() =>
    Object.values(known.value)
      .filter((job) => job.state === "queued" || job.state === "running")
      .map((job) => ({ ...job, label: labels[job.id] })),
  );

  function connected() {
    return socket !== null && socket.readyState === 1;
  }

  function connect(Socket: SocketFactory = WebSocket) {
    factory = Socket;
    const scheme = typeof location !== "undefined" && location.protocol === "https:" ? "wss" : "ws";
    const host = typeof location !== "undefined" ? location.host : "localhost";
    const current = new Socket(`${scheme}://${host}/api/ws`);
    socket = current;
    // A job may have finished while the socket was down; nothing will be pushed for it, so ask once.
    current.onopen = () => {
      poll(true);
    };
    current.onmessage = (event: MessageEvent | { data: string }) => {
      const message = JSON.parse(String(event.data));
      if (message.type === "job") update(message.job as Job);
    };
    current.onclose = (event: CloseEvent | { code: number }) => {
      if (socket === current) socket = null;
      if (event.code === 4401) {
        notifyUnauthorized();
        return;
      }
      setTimeout(() => {
        if (socket === null && factory) connect(factory);
      }, RECONNECT_MS);
    };
  }

  function disconnect() {
    factory = null;
    socket?.close();
    socket = null;
  }

  function finished(job: Job | undefined): boolean {
    return job !== undefined && (job.state === "done" || job.state === "failed" || job.state === "cancelled");
  }

  function settle(job: Job) {
    const waiter = waiters.get(job.id);
    if (!waiter) return;
    waiters.delete(job.id);
    if (job.state === "done") waiter.resolve(job);
    else waiter.reject(new ApiError(0, job.state === "cancelled" ? t("jobs.cancelled") : job.error ?? t("jobs.failed")));
    stopPollingIfIdle();
  }

  function update(job: Job) {
    const before = known.value[job.id];
    known.value = { ...known.value, [job.id]: job };
    if (!finished(job)) return;
    settle(job);
    // Failed jobs may have changed things too (half a batch published), so pages refresh either way.
    if (!finished(before)) {
      for (const listener of listeners) if (listener.kinds.includes(job.kind)) listener.callback(job);
    }
  }

  function stopPollingIfIdle() {
    if (waiters.size === 0 && polling) {
      clearInterval(polling);
      polling = null;
    }
  }

  async function poll(force = false) {
    if (connected() && !force) return;
    for (const id of [...waiters.keys()]) {
      try {
        update(await api.get(id));
      } catch (error) {
        // Jobs live in the server's memory: a 404 means it restarted and the job is gone for good.
        if (error instanceof ApiError && error.status === 404) {
          settle({ id, state: "failed", error: t("jobs.lost") } as Job);
        }
      }
    }
  }

  async function submit(started: Promise<JobRef>, label: string): Promise<Job> {
    const { job_id: id } = await started;
    labels[id] = label;
    const result = new Promise<Job>((resolve, reject) => waiters.set(id, { resolve, reject }));
    const seen = known.value[id];
    if (finished(seen)) settle(seen); // it finished before we got its id
    else if (!seen) update(await api.get(id).catch(() => ({ id, state: "queued" }) as Job));
    if (waiters.has(id) && !polling) polling = setInterval(poll, POLL_MS);
    return result;
  }

  function onFinished(kinds: string[], callback: Listener): () => void {
    const entry = { kinds, callback };
    listeners.push(entry);
    return () => listeners.splice(listeners.indexOf(entry), 1);
  }

  function cancel(id: number) {
    return api.cancel(id).then(update);
  }

  return { running, connect, disconnect, submit, onFinished, cancel };
});

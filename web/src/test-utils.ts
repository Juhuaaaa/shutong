/** Test helpers: a fake fetch keyed by "METHOD path" and a controllable WebSocket. */
import { vi } from "vitest";

export type Handler = (body: unknown, url: URL) => unknown;

export function fakeApi(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body: unknown; url: URL }[] = [];
  const fetchMock = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
    const path = decodeURIComponent(url.pathname);
    calls.push({ method, path, body, url });
    const key = `${method} ${path}`;
    if (!(key in routes)) return new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 });
    let answer = routes[key];
    if (typeof answer === "function") answer = await (answer as Handler)(body, url);
    if (answer instanceof Response) return answer;
    return new Response(answer === undefined ? null : JSON.stringify(answer), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function status(code: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), { status: code });
}

export class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  readyState = 0;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  send() {}
  close() {
    this.readyState = 3;
  }
  push(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

export function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

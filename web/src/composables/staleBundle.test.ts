import { describe, expect, it, vi } from "vitest";
import { reloadOnStaleBundle } from "./staleBundle";

function fakeStorage() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => void values.set(key, value) };
}

describe("reloadOnStaleBundle", () => {
  it("reloads once when a bundle of an older build is gone, and not again within a minute", () => {
    const target = new EventTarget();
    const reload = vi.fn();
    let now = 1_000_000;
    reloadOnStaleBundle(target, reload, fakeStorage(), () => now);
    const event = new Event("vite:preloadError", { cancelable: true });
    target.dispatchEvent(event);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
    target.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));
    expect(reload).toHaveBeenCalledTimes(1); // a real network problem must not loop
    now += 61_000;
    target.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));
    expect(reload).toHaveBeenCalledTimes(2);
  });
});

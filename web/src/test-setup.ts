localStorage.setItem("shutong.locale", "zh-CN"); // tests read Chinese, whatever language the machine runs in
/** happy-dom gaps Vuetify relies on. */
class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= NoopObserver as unknown as typeof ResizeObserver;
globalThis.IntersectionObserver ??= NoopObserver as unknown as typeof IntersectionObserver;
const viewport = { width: 1024, height: 768, offsetLeft: 0, offsetTop: 0, scale: 1, addEventListener() {}, removeEventListener() {} };
(globalThis as unknown as { visualViewport: unknown }).visualViewport ??= viewport;

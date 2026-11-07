/** The desktop window's native side; null in a plain browser. */
export function bridge(): ShutongBridge | null {
  return window.shutong ?? null;
}

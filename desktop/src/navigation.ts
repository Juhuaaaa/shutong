/** What the window may show itself, and what may go to the system browser. */
export function isAllowedNavigation(url: string, port: number): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" && parsed.hostname === "127.0.0.1" && parsed.port === String(port);
  } catch {
    return false;
  }
}

export function externalAllowed(url: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

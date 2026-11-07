/** A little memory between starts, in a file of its own: never in the database, the backend owns that. */
import { readFileSync, writeFileSync } from "node:fs";
import type { Update } from "./update";

export interface State {
  port?: number;
  lastUpdateCheck?: number;
  knownUpdate?: Update;
}

export function readState(path: string): State {
  try {
    const value = JSON.parse(readFileSync(path, "utf8"));
    return typeof value === "object" && value !== null ? value : {};
  } catch {
    return {};
  }
}

export function writeState(path: string, state: State): void {
  try {
    writeFileSync(path, JSON.stringify(state));
  } catch {
    // only a convenience: next start asks for a new port and checks for updates once more
  }
}

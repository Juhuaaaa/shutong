/** Starts the Python backend and waits for its one line. Everything else it logs goes to its own log file. */
import { ChildProcess, spawn } from "node:child_process";
import { closeSync, mkdirSync, openSync } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";

export const START_TIMEOUT_MS = 60_000; // antivirus software can take its time on a first start
const QUIT_GRACE_MS = 8_000;

export type BackendLine = { port: number } | { error: string; message: string } | null;

export function parseReadyLine(line: string): BackendLine {
  const match = /^SHUTONG_(READY|ERROR) (\{.*\})\s*$/.exec(line);
  if (!match) return null;
  let value: { port?: unknown; code?: unknown; message?: unknown };
  try {
    value = JSON.parse(match[2]);
  } catch {
    return null;
  }
  if (match[1] === "READY") {
    return Number.isInteger(value.port) && (value.port as number) > 0 ? { port: value.port as number } : null;
  }
  return { error: String(value.code ?? "unknown"), message: String(value.message ?? "") };
}

export interface BackendCommand {
  command: string;
  args: string[];
  cwd?: string;
  env: Record<string, string>;
  /** Where a crash before the backend's own logging starts ends up: without it the log folder says nothing. */
  stderrFile?: string;
}

function openStderr(file: string | undefined): number | "ignore" {
  if (!file) return "ignore";
  try {
    mkdirSync(path.dirname(file), { recursive: true });
    return openSync(file, "w");
  } catch {
    return "ignore"; // no place to write must not stop the app from starting
  }
}

export interface Backend {
  port: number;
  process: ChildProcess;
}

export class BackendError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

export function startBackend(start: BackendCommand, timeoutMs = START_TIMEOUT_MS): Promise<Backend> {
  return new Promise((resolve, reject) => {
    const stderr = openStderr(start.stderrFile);
    const child = spawn(start.command, start.args, {
      cwd: start.cwd,
      env: { ...process.env, ...start.env },
      stdio: ["pipe", "pipe", stderr],
      windowsHide: true,
    });
    if (stderr !== "ignore") closeSync(stderr); // the child has its own handle now
    const timer = setTimeout(() => {
      child.kill();
      reject(new BackendError("timeout", "后端启动超时"));
    }, timeoutMs);
    const fail = (error: BackendError) => {
      clearTimeout(timer);
      reject(error);
    };
    child.once("error", (error) => fail(new BackendError("spawn", error.message)));
    child.once("exit", (code) => fail(new BackendError("exit", `后端退出，退出码 ${code}`)));
    createInterface({ input: child.stdout! }).on("line", (line) => {
      const parsed = parseReadyLine(line);
      if (parsed === null) return;
      if ("port" in parsed) {
        clearTimeout(timer);
        resolve({ port: parsed.port, process: child });
      } else {
        fail(new BackendError(parsed.error, parsed.message));
      }
    });
  });
}

/** Closing stdin is what tells it to stop; the kill is for a backend that cannot hear that any more. */
export function stopBackend(backend: Backend): void {
  backend.process.stdin?.end();
  const killer = setTimeout(() => backend.process.kill(), QUIT_GRACE_MS);
  killer.unref();
  backend.process.once("exit", () => clearTimeout(killer));
}

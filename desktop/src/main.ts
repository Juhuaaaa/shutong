import { randomBytes } from "node:crypto";
import { statSync } from "node:fs";
import path from "node:path";
import { app, BrowserWindow, dialog, ipcMain, IpcMainInvokeEvent, Menu, session, shell } from "electron";
import { Backend, BackendCommand, BackendError, startBackend, stopBackend } from "./backend";
import { buildMenu, TUTORIAL_URL } from "./menu";
import { externalAllowed, isAllowedNavigation } from "./navigation";
import { Original, trashOriginals } from "./originals";
import { cacheIsStale, readState, State, writeState } from "./state";
import { isNewer, latestRelease, shouldCheck, Update } from "./update";

const COOKIE = "shutong_session";
const token = randomBytes(32).toString("hex");
const dataDir = () => app.getPath("userData");
const logsDir = () => path.join(dataDir(), "logs");
const statePath = () => path.join(dataDir(), "desktop-state.json");

let backend: Backend | null = null;
let window: BrowserWindow | null = null;
let state: State = {};
let update: Update | null = null;
let quitting = false;
let confirming = false;

function backendCommand(port: number | undefined): BackendCommand {
  const portArgs = port ? ["--port", String(port)] : [];
  const env: Record<string, string> = { SHUTONG_DESKTOP_TOKEN: token, PYTHONUTF8: "1" };
  if (process.env.SHUTONG_DEV_BACKEND) {
    const root = path.resolve(__dirname, "..", "..");
    return {
      command: "uv",
      args: ["run", "--project", path.join(root, "backend"), "python", "-m", "shutong.cli", "--data", dataDir(), "desktop-serve",
        "--web", path.join(root, "web", "dist"), ...portArgs],
      cwd: path.join(root, "backend"),
      env,
    };
  }
  const resources = process.resourcesPath;
  const suffix = process.platform === "win32" ? ".exe" : "";
  // Windows reads archives through its own copy of the library; every macOS comes with libarchive's bsdtar.
  if (process.platform === "win32") env.LIBARCHIVE = path.join(resources, "libarchive", "libarchive-13.dll");
  else env.SHUTONG_BSDTAR = "/usr/bin/bsdtar";
  return {
    command: path.join(resources, "backend", `shutong-backend${suffix}`),
    args: ["--data", dataDir(), "desktop-serve", "--web", path.join(resources, "web"), ...portArgs],
    env,
  };
}

async function api<T>(route: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`http://127.0.0.1:${backend!.port}${route}`, {
    ...init,
    headers: { Cookie: `${COOKIE}=${token}`, "Content-Type": "application/json" },
  });
  if (!response.ok) throw new Error(`${route}: ${response.status}`);
  return (await response.json()) as T;
}

/** Only our own page gets to ask for anything. */
function fromOurPage(event: IpcMainInvokeEvent): boolean {
  const url = event.senderFrame?.url;
  return !!url && !!backend && isAllowedNavigation(url, backend.port);
}

function handle(channel: string, listener: (...args: never[]) => unknown): void {
  ipcMain.handle(channel, (event, ...args) => {
    if (!fromOurPage(event)) throw new Error("not allowed");
    return (listener as (...values: unknown[]) => unknown)(...args);
  });
}

function registerIpc(): void {
  handle("pick-folder", async (defaultPath?: string) => {
    const result = await dialog.showOpenDialog(window!, {
      defaultPath: typeof defaultPath === "string" ? defaultPath : undefined,
      properties: ["openDirectory", "createDirectory"],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  handle("open-path", async (target: string) => {
    // Folders only: opening a file would run it.
    if (typeof target === "string" && statSync(target, { throwIfNoEntry: false })?.isDirectory()) {
      await shell.openPath(target);
    }
  });
  handle("default-library-dir", (kind: string) =>
    path.join(app.getPath("documents"), "书童库", kind === "novel" ? "轻小说" : "漫画"));
  handle("open-external", (url: string) => {
    if (typeof url === "string" && externalAllowed(url)) void shell.openExternal(url);
  });
  handle("get-update", () => update);
  handle("trash-originals", (ids: number[]) => trashOriginals(Array.isArray(ids) ? ids : [], {
    originals: async () => (await api<{ items: Original[] }>("/api/desktop/originals")).items,
    trash: (target) => shell.trashItem(target),
    trashed: async (done) => (await api<{ empty_dirs: string[] }>("/api/desktop/originals/trashed", {
      method: "POST",
      body: JSON.stringify({ ids: done }),
    })).empty_dirs,
  }));
}

function createWindow(): void {
  window = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 720,
    minHeight: 520,
    title: "书童",
    show: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  const contents = window.webContents;
  contents.setWindowOpenHandler(({ url }) => {
    if (externalAllowed(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (backend && isAllowedNavigation(url, backend.port)) return;
    event.preventDefault();
    if (externalAllowed(url)) void shell.openExternal(url);
  });
  window.on("close", (event) => {
    if (quitting || !backend) return;
    event.preventDefault();
    void confirmClose();
  });
  void window.loadFile(path.join(__dirname, "loading.html"));
}

async function confirmClose(): Promise<void> {
  if (confirming) return;
  confirming = true;
  try {
    await askAndQuit();
  } finally {
    confirming = false;
  }
}

async function askAndQuit(): Promise<void> {
  const jobs = await api<{ state: string }[]>("/api/jobs").catch(() => []);
  if (jobs.some((job) => job.state === "queued" || job.state === "running")) {
    const answer = await dialog.showMessageBox(window!, {
      type: "warning",
      buttons: ["退出", "继续整理"],
      defaultId: 1,
      cancelId: 1,
      message: "还在整理文件",
      detail: "现在退出会中断整理。原文件不受影响，下次打开后可以重新拖入，继续处理没整理完的文件。",
    });
    if (answer.response !== 0) return;
  }
  quitting = true;
  app.quit();
}

function checkForUpdate(): void {
  const now = Date.now();
  const known = state.knownUpdate;
  if (known && isNewer(known.version, app.getVersion())) announce(known);
  if (!shouldCheck(state.lastUpdateCheck, now)) return;
  void latestRelease(fetch).then((found) => {
    state = { ...state, lastUpdateCheck: now, knownUpdate: found ?? state.knownUpdate };
    writeState(statePath(), state);
    if (found && isNewer(found.version, app.getVersion())) announce(found);
  });
}

function announce(found: Update): void {
  update = found;
  window?.webContents.send("update", found);
}

async function failed(error: unknown): Promise<void> {
  const code = error instanceof BackendError ? error.code : "unknown";
  const message = code === "schema_too_new"
    ? "这份数据是更新版本的书童留下的。请安装最新版本再打开。"
    : `书童没能启动（${(error as Error).message}）。可能是被杀毒软件拦截了，详情请看日志。`;
  const answer = await dialog.showMessageBox({ type: "error", message: "启动失败", detail: message, buttons: ["打开日志目录", "安装教程", "退出"], defaultId: 2, cancelId: 2 });
  if (answer.response === 0) await shell.openPath(logsDir());
  if (answer.response === 1) await shell.openExternal(TUTORIAL_URL);
  quitting = true;
  app.quit();
}

async function start(): Promise<void> {
  state = readState(statePath());
  Menu.setApplicationMenu(buildMenu({ logsDir: logsDir() }));
  registerIpc();
  createWindow();
  try {
    backend = await startBackend({ ...backendCommand(state.port), stderrFile: path.join(logsDir(), "backend-stderr.log") });
    backend.process.once("exit", () => {
      if (!quitting) void failed(new Error("后端意外退出"));
    });
    if (cacheIsStale(state, app.getVersion())) {
      // An upgrade renames the page's bundles: a page cached by the last version would ask for files that are gone.
      await session.defaultSession.clearCache();
    }
    state = { ...state, port: backend.port, appVersion: app.getVersion() };
    writeState(statePath(), state);
    const origin = `http://127.0.0.1:${backend.port}`;
    await session.defaultSession.cookies.set({ url: origin, name: COOKIE, value: token, httpOnly: true, sameSite: "strict" });
    await window!.loadURL(origin);
    checkForUpdate();
  } catch (error) {
    await failed(error);
  }
}

if (!app.requestSingleInstanceLock()) {
  quitting = true;
  app.quit();
} else {
  app.on("second-instance", () => {
    if (window?.isMinimized()) window.restore();
    window?.focus();
  });
  app.on("window-all-closed", () => app.quit());
  // Cmd+Q and the Dock land here, the window's close button in the window's own handler: both ask first.
  app.on("before-quit", (event) => {
    if (quitting || !backend) {
      quitting = true;
      return;
    }
    event.preventDefault();
    void confirmClose();
  });
  app.on("will-quit", () => {
    if (backend) stopBackend(backend);
  });
  void app.whenReady().then(start);
}

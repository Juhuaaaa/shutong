// What must work in a packaged backend, on the machine that built it.
// Usage: node smoke.mjs <backend-exe> [libarchive-dll]    (the DLL on Windows; elsewhere the system's bsdtar is used)
import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const [backend, library] = process.argv.slice(2);
const fixtures = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "smoke", "fixtures");
const work = mkdtempSync(path.join(tmpdir(), "shutong-smoke-"));
const TOKEN = "smoke-token-0123456789";
const failures = [];
const check = (name, ok, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name} ${ok ? "" : detail}`);
  if (!ok) failures.push(name);
};

const env = { ...process.env, PYTHONUTF8: "1", ...(library ? { LIBARCHIVE: library } : { SHUTONG_BSDTAR: "/usr/bin/bsdtar" }) };
const selftest = (...args) => spawnSync(backend, ["desktop-selftest", ...args], { encoding: "utf8", env });

// A Windows runner's code page is 1252, where these names do not exist:
// passing there means they work whatever the user's system language is.
const named = (fixture) => {
  const target = path.join(work, `迷宫饭 ガンダム 第1卷 👋 ${fixture}`);
  copyFileSync(path.join(fixtures, fixture), target);
  return target;
};
const expectNames = (fixture, wanted) => {
  const result = selftest(named(fixture), "--list");
  const names = result.status === 0 ? JSON.parse(result.stdout).names.map((name) => name.normalize("NFC")) : [];
  check(`${fixture}: names intact`, wanted.every((name) => names.includes(name)), result.stdout + result.stderr);
};
expectNames("rar4-plain.rar", ["testdir/test.txt"]);
expectNames("rar4-unicode.rar", ["表だよ/漢字長いファイル名long-filename-in-漢字.txt"]);
expectNames("rar5.rar", ["test.bin"]);
expectNames("rar5-unicode.rar", ["👋🌎.txt"]);
expectNames("lzma2.7z", ["file1"]);
expectNames("unicode.7z", ["第01页.jpg", "ガンダム/02.jpg"]);
const read = selftest(named("unicode.7z"));
check("reads pages of a 7z through the backend's own code", read.status === 0 && read.stdout.includes('"pages": 2'), read.stdout + read.stderr);

const child = spawn(backend, ["--data", path.join(work, "data"), "desktop-serve"], {
  env: { ...env, SHUTONG_DESKTOP_TOKEN: TOKEN }, stdio: ["pipe", "pipe", "inherit"], windowsHide: true,
});
const port = await new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("no handshake in 120 s")), 120_000);
  createInterface({ input: child.stdout }).on("line", (line) => {
    const match = /^SHUTONG_READY (\{.*\})/.exec(line);
    if (match) { clearTimeout(timer); resolve(JSON.parse(match[1]).port); }
  });
  child.once("exit", (code) => reject(new Error(`backend exited with ${code}`)));
});
check("handshake", port > 0);
const base = `http://127.0.0.1:${port}`;
const wrong = await fetch(`${base}/api/libraries`, { headers: { Cookie: "shutong_session=wrong" } });
check("wrong token is refused", wrong.status === 401, String(wrong.status));
const right = await fetch(`${base}/api/libraries`, { headers: { Cookie: `shutong_session=${TOKEN}` } });
check("right token gets in", right.status === 200, String(right.status));
child.removeAllListeners("exit");
const exited = new Promise((resolve) => child.once("exit", resolve));
child.stdin.end();
const code = await Promise.race([exited, new Promise((resolve) => setTimeout(() => resolve("timeout"), 15_000))]);
check("exits when its stdin closes", code === 0, String(code));
if (code === "timeout") child.kill();
try { rmSync(work, { recursive: true, force: true }); } catch { /* still locked on Windows: the temp dir cleans itself */ }
process.exit(failures.length ? 1 : 0);

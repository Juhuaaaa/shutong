// The backend as a folder: desktop/build-backend/dist/shutong-backend.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const result = spawnSync("uv", ["run", "--project", "../backend", "--no-dev", "--with", "pyinstaller==6.*", "pyinstaller", "backend.spec",
  "--noconfirm", "--distpath", "build-backend/dist", "--workpath", "build-backend/work"], { cwd: desktop, stdio: "inherit" });
process.exit(result.status ?? 1);

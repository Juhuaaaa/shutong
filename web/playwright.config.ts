import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const data = resolve("test-results/e2e");
const port = 8791;
const aiPort = 8795;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: { baseURL: `http://127.0.0.1:${port}`, screenshot: "only-on-failure" },
  webServer: [
    {
      command: `uv run --project ../backend python e2e/fixtures.py ${data} && uv run --project ../backend shutong --data ${data}/data `
        + `serve --host 127.0.0.1 --port ${port} --web dist --offline-metadata ${data}/subjects.json`,
      url: `http://127.0.0.1:${port}/api/auth/status`,
      reuseExistingServer: false,
      env: { NO_PROXY: "*", no_proxy: "*" },
    },
    {
      // Recognition needs an AI: a local stand-in that answers like a model would on the fixture names.
      command: `python3 e2e/fake_ai.py ${aiPort}`,
      url: `http://127.0.0.1:${aiPort}/`,
      reuseExistingServer: false,
    },
  ],
});

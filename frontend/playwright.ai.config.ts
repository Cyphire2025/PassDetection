import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
import { isolatedE2eProcessEnvironment } from "./config/e2e-isolation";

// Dedicated ports keep this visual preview independent of other active QA runs.
const appPort = 3126;
const apiPort = 3226;
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const production = process.env.AI_PREVIEW_PRODUCTION === "1";

export default defineConfig({
  ...base,
  testMatch: ["**/ai-voice-preview.spec.ts", "**/ai-assistant-workspace.spec.ts", "**/ai-assistant-access.spec.ts"],
  workers: 1,
  projects: base.projects?.map((project) => ({
    ...project, use: { ...project.use, viewport: { width: 1440, height: 960 } },
  })),
  use: { ...base.use, baseURL: `http://127.0.0.1:${appPort}`, viewport: { width: 1440, height: 960 } },
  webServer: [
    {
      command: `node e2e/support/dashboard-realtime-stub.mjs ${apiPort}`,
      url: `${apiOrigin}/health`, reuseExistingServer: false, timeout: 30_000,
    },
    {
      command: `npm run ${production ? "start" : "dev"} -- --hostname 127.0.0.1 --port ${appPort}`,
      url: `http://127.0.0.1:${appPort}/login`, reuseExistingServer: false, timeout: 120_000,
      env: {
        ...isolatedE2eProcessEnvironment(process.env),
        API_BASE_URL: apiOrigin,
        NEXT_PUBLIC_API_BASE_URL: apiOrigin,
      },
    },
  ],
});

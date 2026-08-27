import { defineConfig, devices } from "@playwright/test";
import {
  E2E_API_ORIGIN,
  E2E_APP_PORT,
  E2E_REALTIME_STUB_PORT,
  isolatedE2eProcessEnvironment,
} from "./config/e2e-isolation";

const isolatedProcessEnvironment = isolatedE2eProcessEnvironment(process.env);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  timeout: 60_000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  // The Next development server compiles routes on demand. Bounding local
  // parallelism prevents a cold server from being flooded by every workspace
  // journey at once, while CI stays serial and deterministic.
  workers: process.env.CI ? 1 : 2,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: `http://127.0.0.1:${E2E_APP_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `node e2e/support/dashboard-realtime-stub.mjs ${E2E_REALTIME_STUB_PORT}`,
      url: `${E2E_API_ORIGIN}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `npm run dev -- --port ${E2E_APP_PORT}`,
      url: `http://127.0.0.1:${E2E_APP_PORT}/login`,
      // Reusing an arbitrary developer server would also reuse its environment
      // and defeat the API-origin isolation above. Fail loudly on port reuse.
      reuseExistingServer: false,
      timeout: 120_000,
      env: isolatedProcessEnvironment,
    },
  ],
});
